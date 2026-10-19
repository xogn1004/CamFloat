"""Bounded ONVIF direction control shared by the app and manual investigation tool.

No presets, lens hiding, audio transmission or cloud account access.
"""
import base64
import datetime as dt
import hashlib
import http.client
import ipaddress
import secrets
import threading
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

SOAP = 'http://www.w3.org/2003/05/soap-envelope'
WSSE = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd'
WSU = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd'
PROFILE = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0'
ENCODING = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0'
DEVICE = 'http://www.onvif.org/ver10/device/wsdl'
MEDIA = 'http://www.onvif.org/ver10/media/wsdl'
PTZ = 'http://www.onvif.org/ver20/ptz/wsdl'
SCHEMA = 'http://www.onvif.org/ver10/schema'
READ_OPERATIONS = {'GetCapabilities', 'GetProfiles', 'GetNodes', 'GetStatus', 'GetPresets',
                   'GetAudioOutputs', 'GetAudioDecoderConfigurations', 'GetAudioOutputConfigurations'}
ALLOWED = READ_OPERATIONS | {'ContinuousMove', 'Stop'}
ERRORS = (OSError, ValueError, http.client.HTTPException, ET.ParseError)
for prefix, namespace in [('s', SOAP), ('wsse', WSSE), ('wsu', WSU), ('tds', DEVICE),
                          ('trt', MEDIA), ('tptz', PTZ), ('tt', SCHEMA)]:
    ET.register_namespace(prefix, namespace)


def element(parent, namespace, name, text=None, **attributes):
    child = ET.SubElement(parent, ET.QName(namespace, name), attributes)
    child.text = text
    return child


def direction_valid(pan, tilt):
    return (type(pan) is int and type(tilt) is int
            and (pan, tilt) in ((-1, 0), (1, 0), (0, -1), (0, 1)))


def envelope(parts, namespace, operation, profile_token=None, pan=None, tilt=0, *, device_timeout_ms=250):
    if operation not in ALLOWED or (pan is not None and not direction_valid(pan, tilt)) or (pan is None and tilt != 0):
        raise ValueError('Unsupported request')
    root = ET.Element(ET.QName(SOAP, 'Envelope'))
    header = element(root, SOAP, 'Header')
    token = element(element(header, WSSE, 'Security'), WSSE, 'UsernameToken')
    nonce = secrets.token_bytes(16)
    created = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + unquote(parts.password or '').encode()).digest()).decode()
    element(token, WSSE, 'Username', unquote(parts.username or ''))
    element(token, WSSE, 'Password', digest, Type=PROFILE + '#PasswordDigest')
    element(token, WSSE, 'Nonce', base64.b64encode(nonce).decode(), EncodingType=ENCODING + '#Base64Binary')
    element(token, WSU, 'Created', created)
    op = element(element(root, SOAP, 'Body'), namespace, operation)
    if operation == 'GetCapabilities':
        element(op, DEVICE, 'Category', 'All')
    if operation in ('Stop', 'ContinuousMove', 'GetStatus', 'GetPresets'):
        if not profile_token:
            raise ValueError('Profile required')
        element(op, PTZ, 'ProfileToken', profile_token)
    if operation == 'Stop':
        element(op, PTZ, 'PanTilt', 'true')
        element(op, PTZ, 'Zoom', 'false')
    if operation == 'ContinuousMove':
        if not direction_valid(pan, tilt):
            raise ValueError('Direction required')
        if type(device_timeout_ms) is not int or not 250 <= device_timeout_ms <= 2000:
            raise ValueError('Unsupported movement duration')
        velocity = element(op, PTZ, 'Velocity')
        element(velocity, SCHEMA, 'PanTilt', x=str(pan), y=str(tilt))
        element(velocity, SCHEMA, 'Zoom', x='0')
        # App steps retain 250ms. Longer values are for the manual comparison.
        element(op, PTZ, 'Timeout', f'PT{device_timeout_ms / 1000:g}S')
    return ET.tostring(root, xml_declaration=True, encoding='utf-8')


def service_path(url, host):
    return service_endpoint(url, host)[0]


def service_endpoint(url, host, *, override_port=None, allow_private_advertisement=False):
    parts = urlsplit(url or '')
    port = parts.port or 80
    same_host = parts.hostname is not None and parts.hostname.casefold() == host.casefold()
    private_advertisement = False
    if allow_private_advertisement and not same_host:
        try:
            address = ipaddress.ip_address(parts.hostname)
            private_advertisement = address.version == 4 and address.is_private and not any((
                address.is_loopback, address.is_link_local, address.is_multicast,
                address.is_unspecified, address.is_reserved))
        except ValueError:
            pass
    if (parts.scheme != 'http' or not (same_host or private_advertisement) or not 1 <= port <= 65535
            or parts.username or parts.password or parts.query or parts.fragment
            or not parts.path.startswith('/') or parts.path.startswith('//') or len(parts.path) > 1024
            or any(ord(c) <= 32 or c == '\\' for c in parts.path)):
        raise ValueError('Untrusted service address')
    return parts.path, override_port if override_port is not None else port


class Client:
    def __init__(self, camera, connection_factory=http.client.HTTPConnection):
        from camfloat.ptz_metadata import control_port
        self.parts = urlsplit(camera['url'])
        self.connection_factory = connection_factory
        self.profile_token = None
        self.ptz_path = None
        self.control_port = control_port(camera)
        try:
            address = ipaddress.ip_address(self.parts.hostname)
            self.remote_route = not address.is_private
        except ValueError:
            self.remote_route = True
        self.fixed_control_port = 'control_port' in camera or self.remote_route
        self.ptz_port = self.control_port

    def build_envelope(self, namespace, operation, pan, tilt, device_timeout_ms):
        return envelope(self.parts, namespace, operation, self.profile_token, pan, tilt,
                        device_timeout_ms=device_timeout_ms)

    def call(self, path, namespace, operation, pan=None, on_sent=None, tilt=0, port=None, timeout=1,
             *, device_timeout_ms=250, attempt=None):
        body = self.build_envelope(namespace, operation, pan, tilt, device_timeout_ms)
        connection = self.connection_factory(self.parts.hostname, port or (self.ptz_port if namespace == PTZ else self.control_port), timeout=timeout)
        result = {'operation': operation, 'response_verified': False, 'request_sent': False}
        root = None
        action = namespace + '/' + operation
        phase = 1  # connect
        try:
            if attempt is not None:
                attempt.start(connection)
                phase = 2  # wait for the shared send phase
                attempt.acquire_write(connection)
                # Connect before the final cancellation gate. A delayed connect
                # must not send an old command after release or a newer command.
                if hasattr(connection, 'timeout'):
                    connection.timeout = min(connection.timeout, max(.001, attempt.remaining()))
                connect = getattr(connection, 'connect', None)
                if connect is not None:
                    phase = 1
                    connect()
                phase = 3  # final cancellation/deadline gate
                attempt.before_request(connection)
            try:
                phase = 4  # write request
                connection.request('POST', path, body, {'Content-Type': 'application/soap+xml; charset=utf-8; action="' + action + '"',
                                                       'SOAPAction': '"' + action + '"', 'Connection': 'close'})
            finally:
                if attempt is not None:
                    attempt.release_write()
            result['request_sent'] = True
            if attempt is not None:
                attempt.request_sent()
            if on_sent:
                on_sent()
            phase = 5  # response headers
            response = connection.getresponse()
            result['http_status'] = response.status
            phase = 6  # response body
            raw = response.read(262145)
            if len(raw) > 262144 or b'<!DOCTYPE' in raw.upper():
                raise ValueError('Invalid SOAP reply')
            phase = 7  # SOAP parsing
            root = ET.fromstring(raw)
            soap_body = root.find('{' + SOAP + '}Body')
            if soap_body is not None:
                fault = soap_body.find('{' + SOAP + '}Fault')
                expected = soap_body.find('{' + namespace + '}' + operation + 'Response')
                result['soap_fault'] = fault is not None
                result['response_verified'] = response.status == 200 and fault is None and expected is not None
        except ERRORS as error:
            result['error'] = type(error).__name__
            result['failure_phase'] = phase
        finally:
            if attempt is not None:
                attempt.finish()
                result['cancelled'] = (attempt.aborted or attempt.cancelled.is_set()) and not result['request_sent']
                result['deadline_exceeded'] = attempt.expired.is_set()
            connection.close()
        return result, root

    def discover(self):
        report = {'capabilities_verified': False, 'profile_verified': False}
        caps = None
        for _ in range(2):
            result, caps = self.call('/onvif/device_service', DEVICE, 'GetCapabilities')
            if result['response_verified']:
                break
        report['capabilities_verified'] = result['response_verified']
        if not result['response_verified']:
            return report
        local = lambda node: node.tag.rsplit('}', 1)[-1]
        services = {}
        for node in caps.iter():
            if local(node) in ('Media', 'PTZ'):
                addr = next((n.text for n in node if local(n) == 'XAddr'), None)
                if addr:
                    try:
                        services[local(node)] = service_endpoint(addr, self.parts.hostname,
                            override_port=self.control_port if self.fixed_control_port else None,
                            allow_private_advertisement=self.remote_route)
                    except ValueError:
                        continue  # Invalid advertisements never change our destination host.
        if 'PTZ' not in services or 'Media' not in services:
            return report
        self.ptz_path, self.ptz_port = services['PTZ']
        for path, port in dict.fromkeys([services['Media'], ('/onvif/media_service', self.control_port)]):
            result, profiles = self.call(path, MEDIA, 'GetProfiles', port=port)
            if not result['response_verified']:
                continue
            for profile in profiles.iter('{' + MEDIA + '}Profiles'):
                ptz = profile.find('{' + SCHEMA + '}PTZConfiguration')
                if ptz is not None and profile.get('token'):
                    self.profile_token = profile.get('token')
                    report['profile_verified'] = True
                    report['ptz_configuration_present'] = True
                    return report
        return report

    def control(self, operation, pan=None, on_sent=None, tilt=0):
        if not self.ptz_path or not self.profile_token:
            raise ValueError('Discovery required')
        return self.call(self.ptz_path, PTZ, operation, pan, on_sent, tilt=tilt)[0]

    def step(self, pan, tilt=0, *, attempt=None):
        """App motion: device timeout only; never wait for or send a Stop."""
        if not self.ptz_path or not self.profile_token or not direction_valid(pan, tilt):
            raise ValueError('Control metadata required')
        return self.call(self.ptz_path, PTZ, 'ContinuousMove', pan=pan, tilt=tilt,
                         timeout=1, attempt=attempt)[0]


def pulse(client, pan, tilt=0, cancelled=None):
    if not direction_valid(pan, tilt):
        raise ValueError('Unsupported direction')
    result = {'pan_sign': pan, 'tilt_sign': tilt, 'requested_ms': 200, 'device_timeout_ms': 250, 'physical_result': 'unconfirmed'}
    cancelled = cancelled if cancelled is not None else threading.Event()
    if cancelled.is_set():
        result['cancelled'] = True
        return result
    def stop():
        cancelled.wait(.2)
        result['timed_stop'] = client.control('Stop')
    timer = threading.Thread(target=stop, name='CamFloat direction stop', daemon=True)
    started = False
    def sent():
        nonlocal started
        timer.start()
        started = True
    try:
        result['move'] = client.control('ContinuousMove', pan, on_sent=sent, tilt=tilt)
    finally:
        try:
            if started:
                timer.join(2)
        finally:
            result['final_stop'] = client.control('Stop')
    return result

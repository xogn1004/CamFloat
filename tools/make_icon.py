from pathlib import Path
import argparse

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser(description='Create the app icon without replacing a supplied ICO.')
    parser.add_argument('--force', action='store_true', help='Regenerate camfloat.ico from camfloat.png')
    args = parser.parse_args()
    project_dir = Path(__file__).resolve().parents[1] / 'assets'
    source = project_dir / "camfloat.png"
    output = project_dir / "camfloat.ico"
    if output.exists() and not args.force:
        with Image.open(output) as image:
            if image.format != 'ICO':
                raise ValueError('camfloat.ico is not a valid ICO file')
            image.load()
        return
    with Image.open(source) as image:
        image.convert("RGBA").save(
            output,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )


if __name__ == "__main__":
    main()

from PIL import Image, ImageDraw


def main() -> None:
    size = 256
    image = Image.new("RGBA", (size, size), (18, 23, 32, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((18, 18, 238, 238), radius=48, fill=(30, 39, 53, 255))
    draw.rounded_rectangle((39, 68, 217, 188), radius=20, fill=(8, 12, 17, 255))
    draw.ellipse((83, 78, 173, 168), fill=(75, 146, 239, 255))
    draw.ellipse((98, 93, 158, 153), fill=(11, 17, 25, 255))
    draw.ellipse((112, 107, 144, 139), fill=(113, 177, 255, 255))
    draw.rounded_rectangle((184, 86, 202, 104), radius=7, fill=(255, 94, 94, 255))
    image.save("camfloat.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()

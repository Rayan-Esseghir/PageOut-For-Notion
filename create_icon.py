#!/usr/bin/env python3
"""Generate PageOut custom icon (ICO and PNG) using Pillow."""

from PIL import Image, ImageDraw
import os

def create_pageout_icon():
    """Create a modern PageOut icon: document page with export arrow."""
    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Calculate dimensions
        margin = max(1, size // 16)
        doc_width = size - 2 * margin
        doc_height = size - 2 * margin
        corner_radius = max(1, size // 16)

        # Document background (rounded rectangle)
        doc_color = (40, 167, 69, 255)  # Modern green #28a745
        draw.rounded_rectangle(
            [margin, margin, size - margin, size - margin],
            radius=corner_radius,
            fill=doc_color
        )

        # White document content area
        content_margin = max(2, size // 12)
        content_top = margin + max(2, size // 8)
        content_bottom = size - margin - max(1, size // 20)
        content_left = margin + content_margin
        content_right = size - margin - content_margin

        # Draw lines representing text content
        line_color = (255, 255, 255, 230)
        line_height = max(1, size // 32)
        line_spacing = max(2, size // 16)
        num_lines = max(3, size // 24)

        for i in range(num_lines):
            y = content_top + i * (line_height + line_spacing)
            if y + line_height > content_bottom:
                break
            # Vary line widths for realism
            if i == 0:
                # Title line - shorter
                line_width = doc_width * 0.6
            elif i == num_lines - 1:
                # Last line - shorter
                line_width = doc_width * 0.4
            else:
                line_width = doc_width * 0.9

            line_left = content_left + (doc_width - line_width) / 2
            line_right = line_left + line_width
            draw.rounded_rectangle(
                [line_left, y, line_right, y + line_height],
                radius=max(1, line_height // 2),
                fill=line_color
            )

        # Export arrow (right side)
        arrow_size = max(6, size // 5)
        arrow_center_x = size - margin - arrow_size // 2
        arrow_center_y = size // 2

        # Arrow shaft
        shaft_width = max(2, size // 16)
        shaft_length = arrow_size * 0.7
        shaft_left = arrow_center_x - shaft_width // 2
        shaft_right = arrow_center_x + shaft_width // 2
        shaft_top = arrow_center_y - shaft_length // 2
        shaft_bottom = arrow_center_y + shaft_length // 2 - arrow_size // 3

        draw.rectangle([shaft_left, shaft_top, shaft_right, shaft_bottom], fill="white")

        # Arrow head (triangle)
        head_size = max(4, size // 10)
        head_points = [
            (arrow_center_x, arrow_center_y + shaft_length // 2),  # tip
            (arrow_center_x - head_size, shaft_bottom),  # left
            (arrow_center_x + head_size, shaft_bottom),  # right
        ]
        draw.polygon(head_points, fill="white")

        # Small circle/accent at top-left of document
        accent_size = max(2, size // 16)
        draw.ellipse(
            [margin + 2, margin + 2, margin + 2 + accent_size * 2, margin + 2 + accent_size * 2],
            fill=(255, 255, 255, 180)
        )

        images.append(img)

    # Save as ICO (Windows multi-resolution) - use largest image as base so all sizes can be included
    ico_path = "pageout/assets/pageout.ico"
    os.makedirs(os.path.dirname(ico_path), exist_ok=True)
    images[-1].save(
        ico_path,
        format="ICO",
        sizes=[(img.width, img.height) for img in images],
        append_images=images[:-1]
    )
    print(f"Created {ico_path} with sizes: {[img.size for img in images]}")

    # Save as PNG (256x256 as main)
    png_path = "pageout/assets/pageout.png"
    images[-1].save(png_path, format="PNG")
    print(f"Created {png_path} ({images[-1].size})")

    # Also create a simple icon.ico and icon.png for backward compatibility
    # (the existing code looks for "icon.ico", "icon.png", etc.)
    images[-1].save(
        "pageout/assets/icon.ico",
        format="ICO",
        sizes=[(img.width, img.height) for img in images],
        append_images=images[:-1]
    )
    images[-1].save("pageout/assets/icon.png", format="PNG")
    print(f"Created backward-compatible icon.ico and icon.png")

if __name__ == "__main__":
    create_pageout_icon()
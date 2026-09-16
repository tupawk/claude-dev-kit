#!/usr/bin/env python3
# ruff: noqa
# Vendored tool from claude-dev-kit, not project source. Kept identical across projects and
# updated only through the kit, so project lint rules do not apply here. Ruff-formatted.
"""
check_logo_aspect.py - flag stretched logos and images in .pptx and .docx deliverables.

Compares every placed image's on-slide (or on-page) aspect ratio against the native
aspect ratio of the underlying image file. Anything outside tolerance is stretched.

Usage:
    python3 check_logo_aspect.py deck.pptx
    python3 check_logo_aspect.py report.docx --all
    python3 check_logo_aspect.py deck.pptx --tolerance 0.005

Options:
    --all              List every image, not just the distorted ones
    --tolerance FLOAT  Allowed relative deviation (default 0.01 = 1%)

Exit code 0 = clean, 1 = distortion found, 2 = could not read the file.
Requires: pillow  (pip install pillow --break-system-packages)
"""

import argparse
import io
import os
import posixpath
import sys
import zipfile
import xml.etree.ElementTree as ET

from PIL import Image

EMU_PER_INCH = 914400.0

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
R_EMBED = "{%s}embed" % NS["r"]

# Add your own logo files here, keyed by native pixel size, to label findings. Optional.
KNOWN_LOGOS: dict = {}
LOGO_NAME_HINTS = ("logo", "brand", "mark", "wordmark")


def load_rels(zf, part_name):
    """Return {rId: target_part_name} for a given part."""
    folder, base = posixpath.split(part_name)
    rels_name = posixpath.join(folder, "_rels", base + ".rels")
    if rels_name not in zf.namelist():
        return {}
    rels = {}
    root = ET.fromstring(zf.read(rels_name))
    for rel in root.findall("rel:Relationship", NS):
        target = rel.get("Target", "")
        if target.startswith("/"):
            resolved = target.lstrip("/")
        elif "://" in target:
            continue
        else:
            resolved = posixpath.normpath(posixpath.join(folder, target))
        rels[rel.get("Id")] = resolved
    return rels


def native_size(zf, part_name, cache):
    if part_name in cache:
        return cache[part_name]
    try:
        with Image.open(io.BytesIO(zf.read(part_name))) as im:
            cache[part_name] = im.size
    except Exception:
        cache[part_name] = None
    return cache[part_name]


def content_parts(zf):
    """Parts worth inspecting, in a sensible reporting order."""
    names = zf.namelist()
    wanted = []
    for n in sorted(names):
        if n.startswith("ppt/slides/slide") and n.endswith(".xml"):
            wanted.append(n)
        elif n.startswith("ppt/slideLayouts/slideLayout") and n.endswith(".xml"):
            wanted.append(n)
        elif n.startswith("ppt/slideMasters/slideMaster") and n.endswith(".xml"):
            wanted.append(n)
        elif n == "word/document.xml":
            wanted.append(n)
        elif n.startswith("word/header") or n.startswith("word/footer"):
            if n.endswith(".xml"):
                wanted.append(n)
    return wanted


def blip_in(el):
    blip = el.find(".//a:blip", NS)
    return blip.get(R_EMBED) if blip is not None else None


def find_placements(zf, part_name):
    """Yield (label, rId, cx, cy) for each placed picture in the part."""
    root = ET.fromstring(zf.read(part_name))

    # PresentationML pictures
    for idx, pic in enumerate(root.iter("{%s}pic" % NS["p"]), start=1):
        rid = blip_in(pic)
        ext = pic.find(".//a:xfrm/a:ext", NS)
        if not rid or ext is None:
            continue
        name_el = pic.find(".//p:nvPicPr/p:cNvPr", NS)
        shape_name = name_el.get("name") if name_el is not None else ""
        label = shape_name or "picture %d" % idx
        yield label, rid, int(ext.get("cx")), int(ext.get("cy"))

    # WordprocessingML drawings (inline and floating)
    for tag in ("inline", "anchor"):
        for idx, dr in enumerate(root.iter("{%s}%s" % (NS["wp"], tag)), start=1):
            rid = blip_in(dr)
            ext = dr.find("wp:extent", NS)
            if not rid or ext is None:
                continue
            doc_pr = dr.find("wp:docPr", NS)
            shape_name = doc_pr.get("name") if doc_pr is not None else ""
            label = shape_name or "%s image %d" % (tag, idx)
            yield label, rid, int(ext.get("cx")), int(ext.get("cy"))


def part_display(part_name):
    base = posixpath.basename(part_name)
    if part_name.startswith("ppt/slides/"):
        return "Slide " + base.replace("slide", "").replace(".xml", "")
    if part_name.startswith("ppt/slideLayouts/"):
        return "Layout " + base.replace("slideLayout", "").replace(".xml", "")
    if part_name.startswith("ppt/slideMasters/"):
        return "Master " + base.replace("slideMaster", "").replace(".xml", "")
    if part_name == "word/document.xml":
        return "Document body"
    return base.replace(".xml", "").capitalize()


def describe(media_part, size):
    if size in KNOWN_LOGOS:
        return KNOWN_LOGOS[size], True
    base = posixpath.basename(media_part).lower()
    if any(h in base for h in LOGO_NAME_HINTS):
        return "possible logo (%s)" % posixpath.basename(media_part), True
    return posixpath.basename(media_part), False


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("path")
    ap.add_argument("--all", action="store_true", help="list every image, not just distorted ones")
    ap.add_argument(
        "--tolerance", type=float, default=0.01, help="allowed deviation (default 0.01)"
    )
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        print("Cannot find file: %s" % args.path)
        return 2
    if not zipfile.is_zipfile(args.path):
        print("Not a .pptx or .docx file: %s" % args.path)
        return 2

    findings = []
    checked = 0
    cache = {}

    with zipfile.ZipFile(args.path) as zf:
        for part in content_parts(zf):
            rels = load_rels(zf, part)
            try:
                placements = list(find_placements(zf, part))
            except ET.ParseError:
                continue
            for label, rid, cx, cy in placements:
                media = rels.get(rid)
                if not media:
                    continue
                size = native_size(zf, media, cache)
                if not size or cx <= 0 or cy <= 0:
                    continue
                checked += 1
                nat_ratio = size[0] / size[1]
                placed_ratio = cx / cy
                dev = abs(placed_ratio - nat_ratio) / nat_ratio
                name, is_logo = describe(media, size)
                findings.append(
                    {
                        "where": part_display(part),
                        "shape": label,
                        "name": name,
                        "is_logo": is_logo,
                        "nat": nat_ratio,
                        "placed": placed_ratio,
                        "dev": dev,
                        "w_in": cx / EMU_PER_INCH,
                        "h_in": cy / EMU_PER_INCH,
                        "fix_h_in": (cx / nat_ratio) / EMU_PER_INCH,
                    }
                )

    bad = [f for f in findings if f["dev"] > args.tolerance]
    show = findings if args.all else bad

    print("\nAspect ratio check: %s" % os.path.basename(args.path))
    print(
        "Images checked: %d   Distorted: %d   Tolerance: %.1f%%\n"
        % (checked, len(bad), args.tolerance * 100)
    )

    if not show:
        print("No distorted images found. All placed images match their native aspect ratio.\n")
        return 0

    for f in sorted(show, key=lambda x: -x["dev"]):
        status = "STRETCHED" if f["dev"] > args.tolerance else "ok"
        tag = " [LOGO]" if f["is_logo"] else ""
        print("%-11s %s | %s%s" % (status, f["where"], f["shape"], tag))
        print("             file: %s" % f["name"])
        print(
            "             placed %.3f in x %.3f in  (ratio %.3f), native ratio %.3f, off by %.1f%%"
            % (f["w_in"], f["h_in"], f["placed"], f["nat"], f["dev"] * 100)
        )
        if f["dev"] > args.tolerance:
            print(
                "             FIX: keep width %.3f in, set height to %.3f in"
                % (f["w_in"], f["fix_h_in"])
            )
        print()

    if bad:
        print("Fix every STRETCHED item above before the file is delivered.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

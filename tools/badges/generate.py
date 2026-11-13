#!/usr/bin/env python3
"""Generate self-contained flat-square SVG badges from badges.json and local SVG logos."""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

SVG_NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG_NS)
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
SAFE_ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')


def validate_color(value, field):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError(f'{field} must be a #RRGGBB color')
    return value


def text_width(text, font_size):
    # Conservative per-character estimate for Arial/DejaVu Sans, no external font dependency.
    weights = {'i': .28, 'l': .28, 'I': .30, 'j': .30, 't': .38, 'f': .36,
               'r': .38, 'm': .83, 'w': .78, 'M': .83, 'W': .94,
               ' ': .29, '.': .29, '-': .35, '_': .55}
    return sum(weights.get(ch, .59 if ch.isupper() else .53) for ch in text) * font_size


def svg_logo(path, x, y, size):
    root = ET.parse(path).getroot()
    if root.tag != f'{{{SVG_NS}}}svg':
        raise ValueError(f'{path}: root element must be <svg>')
    if root.find('.//{http://www.w3.org/2000/svg}script') is not None:
        raise ValueError(f'{path}: SVG scripts are not allowed')
    # SVG logos are trusted local inputs. Strip event handlers and external references.
    for el in root.iter():
        for key, value in list(el.attrib.items()):
            local = key.split('}')[-1].lower()
            if local.startswith('on') or local == 'href' and (value.startswith('http:') or value.startswith('https:') or value.startswith('//')):
                raise ValueError(f'{path}: unsafe SVG attribute {key}')
        if el.tag.split('}')[-1].lower() in ('foreignObject'.lower(), 'image', 'use'):
            raise ValueError(f'{path}: external/image/use elements are unsupported')
    viewbox = root.get('viewBox')
    if not viewbox:
        width, height = root.get('width', ''), root.get('height', '')
        if not width.isdigit() or not height.isdigit():
            raise ValueError(f'{path}: logo needs viewBox or integer width/height')
        viewbox = f'0 0 {width} {height}'
    root.set('x', str(x))
    root.set('y', str(y))
    root.set('width', str(size))
    root.set('height', str(size))
    root.set('viewBox', viewbox)
    root.set('preserveAspectRatio', 'xMidYMid meet')
    root.attrib.pop('xmlns', None)
    return ET.tostring(root, encoding='unicode')


def generate_badge(item, config, logos_dir):
    badge_id = item.get('id')
    if not isinstance(badge_id, str) or not SAFE_ID.fullmatch(badge_id):
        raise ValueError(f'Invalid badge id: {badge_id!r}')
    label = item.get('label')
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f'{badge_id}: label must be a nonempty string')
    if any(ord(c) < 32 for c in label):
        raise ValueError(f'{badge_id}: control characters in label')
    # Backward compatible: "color" remains the label background fallback.
    label_bg = validate_color(
        item.get('label_background', item.get('color')),
        f'{badge_id}.label_background')
    logo_bg = validate_color(
        item.get('logo_background', label_bg),
        f'{badge_id}.logo_background')
    fg = validate_color(item.get('text_color', '#FFFFFF'), f'{badge_id}.text_color')
    height = config.get('height', 20)
    if type(height) is not int or not 16 <= height <= 80:
        raise ValueError('height must be an integer from 16 to 80')
    font_size = round(height * .55, 1)
    padding = round(height * .45)
    logo_size = round(height * .72)
    logo_name = item.get('logo')
    logo_xml = ''
    logo_section_width = 0
    if logo_name is not None:
        if (not isinstance(logo_name, str) or Path(logo_name).name != logo_name
                or not logo_name.lower().endswith('.svg')):
            raise ValueError(f'{badge_id}: logo must be an SVG filename without directories')
        path = logos_dir / logo_name
        if not path.is_file():
            raise FileNotFoundError(f'{badge_id}: logo not found: {path}')
        logo_section_width = logo_size + 2 * padding
        logo_xml = svg_logo(path, padding, (height - logo_size) // 2, logo_size)
    text_x = logo_section_width + padding
    width = int(text_x + text_width(label, font_size) + padding + 2.5)
    baseline = round(height * .70, 2)
    safe_label = escape(label, {'"': '&quot;'})
    parts = [
        f'<svg xmlns="{SVG_NS}" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{safe_label}">',
        f'  <title>{safe_label}</title>',
        f'  <rect width="{width}" height="{height}" fill="{label_bg}"/>',
    ]
    if logo_xml:
        parts.extend([
            f'  <rect width="{logo_section_width}" height="{height}" fill="{logo_bg}"/>',
            f'  {logo_xml}',
        ])
    parts.extend([
        f'  <text x="{text_x}" y="{baseline}" fill="{fg}" '
        f'font-family="Arial,DejaVu Sans,sans-serif" font-size="{font_size}" '
        f'font-weight="600">{safe_label}</text>',
        '</svg>',
        '',
    ])
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Path to badges.json (default: next to this script)')
    args = parser.parse_args()
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent
    config_path = args.config.resolve() if args.config else script_dir / 'badges.json'
    logos_dir = project_root / 'assets' / 'logos'
    out_dir = project_root / 'assets' / 'badges'
    try:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if config.get('style', 'flat-square') != 'flat-square':
            raise ValueError('Only flat-square style is supported')
        badges = config.get('badges')
        if not isinstance(badges, list):
            raise ValueError('badges must be an array')
        generated = {}
        for item in badges:
            svg = generate_badge(item, config, logos_dir)
            name = item['id'] + '.svg'
            if name in generated:
                raise ValueError(f'Duplicate badge id: {item["id"]}')
            generated[name] = svg
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, svg in generated.items():
            (out_dir / name).write_text(svg, encoding='utf-8')
            print(f'Generated: {out_dir / name}')
        print(f'Done: {len(generated)} badge(s).')
    except (ValueError, OSError, ET.ParseError, json.JSONDecodeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

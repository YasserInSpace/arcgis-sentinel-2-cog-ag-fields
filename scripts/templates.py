"""
templates.py
Resolves which raster function templates get attached to a mosaic dataset.

The full template set is vegetation-heavy and not all of it is relevant to any
one job, so templates are grouped into packs that config selects by name. The
resolved list is written into a per-run copy of the MDCS config XML, leaving the
checked-in config untouched.
"""

import os
import shutil
from xml.dom import minidom


PACKS = {
    'imagery': [
        'Natural Color with DRA.rft.xml',
        'Natural Color.rft.xml',
        'Color Infrared with DRA.rft.xml',
        'Color Infrared.rft.xml',
        'Short-wave Infrared with DRA.rft.xml',
        'Short-wave Infrared.rft.xml',
    ],
    'vegetation': [
        'NDVI Colormap.rft.xml',
        'NDVI Raw.rft.xml',
        'NDVI - VRE only Raw.rft.xml',
        'NDVI - VRE only Colorized.rft.xml',
        'NDVI - with VRE Raw.rft.xml',
        'NDVI - with VRE Colorized.rft.xml',
        'Agriculture with DRA.rft.xml',
        'Agriculture.rft.xml',
    ],
    'water': [
        'NDWI Raw.rft.xml',
        'NDWI - with VRE Raw.rft.xml',
        'NDWI - with VRE Colorized.rft.xml',
        'NDMI Colorized.rft.xml',
        'Bathymetric with DRA.rft.xml',
        'Bathymetric.rft.xml',
    ],
    'fire': [
        'Normalized Burn Ratio.rft.xml',
        'Short-wave Infrared with DRA.rft.xml',
        'Short-wave Infrared.rft.xml',
    ],
    'urban': [
        'Normalized Difference Built-Up Index (NDBI).rft.xml',
        'Short-wave Infrared.rft.xml',
        'Natural Color.rft.xml',
    ],
    'geology': [
        'Geology with DRA.rft.xml',
        'Geology.rft.xml',
        'Short-wave Infrared with DRA.rft.xml',
        'Short-wave Infrared.rft.xml',
    ],
    'snow': [
        'NDSI Raw.rft.xml',
        'Natural Color.rft.xml',
    ],
}

# Order used when the "all" pack is requested, so the most generally useful
# renderings come first in the Pro template dropdown.
ALL_ORDER = ['imagery', 'vegetation', 'water', 'fire',
             'urban', 'geology', 'snow']


def available_packs():
    return sorted(PACKS)


def resolve_templates(packs, templates_dir):
    """Resolve pack names into an ordered, de-duplicated template filename list.

    Returns (templates, warnings). Unknown pack names and templates missing from
    disk are reported as warnings rather than raising, so one bad entry does not
    abort a run.
    """
    if isinstance(packs, str):
        packs = [packs]
    if not packs:
        packs = ['all']

    requested = [str(p).strip().lower() for p in packs if str(p).strip()]
    warnings = []

    if 'all' in requested:
        names = list(ALL_ORDER)
    else:
        names = []
        for pack in requested:
            if pack in PACKS:
                names.append(pack)
            else:
                warnings.append(
                    "unknown template pack '%s' (available: %s, all)"
                    % (pack, ', '.join(available_packs()))
                )

    if not names:
        warnings.append('no valid template packs selected; falling back to "all"')
        names = list(ALL_ORDER)

    resolved = []
    for pack in names:
        for template in PACKS[pack]:
            if template in resolved:
                continue
            if not os.path.exists(os.path.join(templates_dir, template)):
                warnings.append("template file not found, skipping: %s" % template)
                continue
            resolved.append(template)

    return resolved, warnings


def write_run_config(source_xml, target_xml, templates):
    """Copy the MDCS config XML, injecting the resolved template list.

    MDCS resolves the raster type and template folders relative to its own code
    base rather than to the config file, so the copy can live anywhere.
    """
    if not templates:
        shutil.copyfile(source_xml, target_xml)
        return target_xml

    document = minidom.parse(source_xml)

    def set_node(tag, value):
        nodes = document.getElementsByTagName(tag)
        if not nodes:
            return
        node = nodes[0]
        if node.firstChild is None:
            node.appendChild(document.createTextNode(value))
        else:
            node.firstChild.data = value

    # "None" stays available so a user can switch rendering off in Pro.
    set_node('processing_templates', ';'.join(templates + ['None']))
    set_node('default_processing_template', templates[0])

    with open(target_xml, 'w', encoding='utf-8') as handle:
        document.writexml(handle)

    return target_xml

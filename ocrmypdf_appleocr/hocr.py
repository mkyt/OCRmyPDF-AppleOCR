from ocrmypdf_appleocr.common import Textbox


def build_hocr_line(textbox: Textbox, page_number: int, line_number: int, lang: str) -> str:
    # Read the fields by name: unpacking the whole tuple breaks as soon as Textbox
    # grows a field, as it did when word-level children were added.
    text, bb, confidence, is_vert = (
        textbox.text,
        textbox.bb,
        textbox.confidence,
        textbox.is_vertical,
    )
    if not is_vert:
        bbox = f"{bb.to_hocr_bbox()}; {bb.estimated_baseline()}"
    else:
        bbox = f"{bb.to_hocr_bbox()}"
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    word_id = f"word_{page_number}_{line_number}"
    word_title = f"{bbox}; x_wconf {confidence}"
    word_span = f'<span class="ocrx_word" id="{word_id}" title="{word_title}">{text}</span>'
    return f"""<div class="ocr_carea" id="block_{page_number}_{line_number}" title="{bbox}">
<p class="ocr_par" id="par_{page_number}_{line_number}" lang="{lang}" title="{bbox}">
  <span class="ocr_line" id="line_{page_number}_{line_number}" title="{bbox}">
    {word_span}
  </span>
</p>
</div>
"""


hocr_template = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head>
<title></title>
<meta http-equiv="Content-Type" content="text/html;charset=utf-8"/>
<meta name="ocr-system" content="" />
<meta name="ocr-capabilities" content="ocr_page ocr_carea ocr_par ocr_line ocrx_word"/>
</head>
<body>
<div class="ocr_page" id="page_0" title="bbox 0 0 {width} {height}">
{content}
</div>
</body>
</html>
"""


def build_hocr_document(ocr_result: list[Textbox], width, height) -> str:
    content = "".join(build_hocr_line(tb, 0, i, "und") for i, tb in enumerate(ocr_result))
    return hocr_template.format(content=content, width=width, height=height)

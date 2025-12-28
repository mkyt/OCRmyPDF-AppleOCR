from ocrmypdf_appleocr.common import Textbox


def build_hocr_line(textbox: Textbox, page_number: int, line_number: int, lang: str) -> str:
    text, bb, confidence, is_vert = textbox
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
    return f"""<div class="ocr_carea" id="block_{page_number}_{line_number}" title="{bbox}">
<p class="ocr_par" id="par_{page_number}_{line_number}" lang="{lang}" title="{bbox}">
  <span class="ocr_line" id="line_{page_number}_{line_number}" title="{bbox}">
    <span class="ocrx_word" id="word_{page_number}_{line_number}" title="{bbox}; x_wconf {confidence}">{text}</span>
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

#!/usr/bin/env python3
from os import listdir
from os.path import basename, splitext, abspath, join
from sys import argv
from markdown import markdown
from xml.dom.minidom import Document
from zipfile import ZipFile, ZIP_DEFLATED
from json import load
from re import sub


def get_image_mimetype(image_name: str) -> str:
    if "gif" in image_name:
        return "image/gif"
    elif "jpg" in image_name:
        return "image/jpeg"
    elif "jpeg" in image_name:
        return "image/jpg"
    elif "png" in image_name:
        return "image/png"

def escape_xml(text: str) -> str:
    return Document().createTextNode(text).toxml()


def create(doc: Document, tag: str, attributes: dict) -> Document:
    element = doc.createElement(tag)
    for key, value in attributes.items():
        element.setAttribute(key, value)

    return element


class EPubGenerator:
    def __init__(self, source_directory: str) -> None:
        self.source_directory = abspath(source_directory)
        settings_path = self.get_path("description.json")

        self.images_directory = self.get_path('images')
        self.styles_directory = self.get_path('css')

        with open(settings_path, "r") as f:
            self.settings_data = load(f)

        self.markdowns = [chapter.copy()
                          for chapter in self.settings_data["chapters"]]

        self.default_styles = self.settings_data["default_css"]
        self.styles = set(self.default_styles)
        self.styles.update([chapter["css"]
                           for chapter in self.markdowns if "css" in chapter])

        self.images = self.find_images()

    def get_path(self, relative_path: str) -> str:
        return join(self.source_directory, relative_path)

    def image_path(self, image_name: str) -> str:
        return join(self.images_directory, image_name)

    def style_path(self, style_name: str) -> str:
        return join(self.styles_directory, style_name)

    def find_images(self):
        extensions = [".gif", ".jpg", ".jpeg", ".png"]
        images = [join('images', basename(image)) for image in listdir(
            self.images_directory) if splitext(image)[1] in extensions]

        return images

    def _create_package(self, doc: Document) -> Document:
        package = doc.createElement('package')
        package.setAttribute('xmlns', "http://www.idpf.org/2007/opf")
        package.setAttribute('version', "3.0")
        package.setAttribute('xml:lang', "en")
        package.setAttribute("unique-identifier", "pub-id")

        return package

    def _create_metadata(self, doc: Document) -> Document:
        metadata = doc.createElement('metadata')
        metadata.setAttribute('xmlns:dc', 'http://purl.org/dc/elements/1.1/')

        metadata_settings = self.settings_data["metadata"]

        for key, value in metadata_settings.items():
            if len(value):
                entry = doc.createElement(key)
                for metadata_type, id_label in [("dc:title", "title"), ("dc:creator", "creator"), ("dc:identifier", "book-id")]:
                    if key == metadata_type:
                        entry.setAttribute('id', id_label)
                entry.appendChild(doc.createTextNode(value))
                metadata.appendChild(entry)

        # Ensure compatibility by providing a cover meta tag in the metadata
        for index, image_name in enumerate(self.images):
            if image_name == self.settings_data["cover_image"]:
                cover = doc.createElement('meta')
                cover.setAttribute('name', "cover")
                cover.setAttribute('content', "image-{:05d}".format(index))
                metadata.appendChild(cover)

        return metadata

    def _create_manifest(self, doc: Document) -> Document:
        manifest = doc.createElement('manifest')

        # TOC.xhtml file for EPUB 3
        toc_xhtml = doc.createElement('item')
        toc_xhtml.setAttribute('id', "toc")
        toc_xhtml.setAttribute('properties', "nav")
        toc_xhtml.setAttribute('href', "TOC.xhtml")
        toc_xhtml.setAttribute('media-type', "application/xhtml+xml")
        manifest.appendChild(toc_xhtml)

        # Ensure retrocompatibility by also providing a TOC.ncx file
        toc_ncx = doc.createElement('item')
        toc_ncx.setAttribute('id', "ncx")
        toc_ncx.setAttribute('href', "toc.ncx")
        toc_ncx.setAttribute('media-type', "application/x-dtbncx+xml")
        manifest.appendChild(toc_ncx)

        title_page = doc.createElement('item')
        title_page.setAttribute('id', "titlepage")
        title_page.setAttribute('href', "titlepage.xhtml")
        title_page.setAttribute('media-type', "application/xhtml+xml")
        manifest.appendChild(title_page)

        for index, markdown in enumerate(self.markdowns):
            base = splitext(basename(markdown['markdown']))[0]
            chapter = doc.createElement('item')
            chapter.setAttribute('id', "s{:05d}".format(index))
            chapter.setAttribute(
                'href', "s{:05d}-{}.xhtml".format(index, base))
            chapter.setAttribute('media-type', "application/xhtml+xml")
            manifest.appendChild(chapter)

        for index, image_name in enumerate(self.images):
            image = doc.createElement('item')
            image.setAttribute('id', "image-{:05d}".format(index))
            image.setAttribute('href', image_name)
            image.setAttribute('media-type', get_image_mimetype(image_name))

            if image_name == self.settings_data["cover_image"]:
                image.setAttribute('properties', "cover-image")

            manifest.appendChild(image)

        for index, style_name in enumerate(self.styles):
            style = doc.createElement('item')
            style.setAttribute('id', "css-{:05d}".format(index))
            style.setAttribute('href', style_name)
            style.setAttribute('media-type', "text/css")
            manifest.appendChild(style)

        return manifest

    def _create_spine(self, doc: Document) -> Document:
        spine = doc.createElement('spine')
        spine.setAttribute('toc', "ncx")

        title_page = doc.createElement('itemref')
        title_page.setAttribute('idref', "titlepage")
        title_page.setAttribute('linear', "yes")
        spine.appendChild(title_page)

        for index, _ in enumerate(self.markdowns):
            chapter = doc.createElement('itemref')
            chapter.setAttribute('idref', "s{:05d}".format(index))
            chapter.setAttribute('linear', "yes")
            spine.appendChild(chapter)

        return spine

    def _create_guide(self, doc: Document) -> Document:
        guide = doc.createElement('guide')
        reference = doc.createElement('reference')
        reference.setAttribute('type', "cover")
        reference.setAttribute('title', "Cover image")
        reference.setAttribute('href', "titlepage.xhtml")
        guide.appendChild(reference)

        return guide

    def packageOPF_XML(self):
        opf = Document()

        package = self._create_package(opf)

        package.appendChild(self._create_metadata(opf))
        package.appendChild(self._create_manifest(opf))
        package.appendChild(self._create_spine(opf))
        package.appendChild(self._create_guide(opf))

        opf.appendChild(package)

        return opf.toprettyxml()

    def container_XML(self) -> bytes:
        return (
            '<?xml version="1.0" encoding="UTF-8" ?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '<rootfiles>\n'
            '<rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/>\n'
            '</rootfiles>\n</container>'
        ).encode('utf-8')

    def coverpage_XML(self) -> bytes:
        # Returns the XML data for the coverpage.xhtml file
        cover_image_path = self.settings_data["cover_image"]
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n' +
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="fr">\n' +
            '<head>\n</head>\n<body>\n' +
            '<img src="{}" style="height:100%;max-width:100%;"/>\n'.format(cover_image_path) +
            '</body>\n</html>'
        ).encode('utf-8')

    def toc_XML(self) -> bytes:
        # Returns the XML data for the TOC.xhtml file
        toc_xhtml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">\n'
            '<head>\n<meta http-equiv="default-style" content="text/html; charset=utf-8"/>\n'
            '<title>Contents</title>\n'
        )

        for style_name in self.default_styles:
            toc_xhtml += '<link rel="stylesheet" href="{}" type="text/css"/>\n'.format(
                style_name)

        toc_xhtml += (
            '</head>\n<body>\n'
            '<nav epub:type="toc" role="doc-toc" id="toc">\n<h2>Contents</h2>\n<ol epub:type="list">'
        )

        for index, markdown in enumerate(self.markdowns):
            base = splitext(basename(markdown["markdown"]))[0]
            title = escape_xml(self.chapter_title(markdown["markdown"]))
            toc_xhtml += '<li><a href="s{:05d}-{}.xhtml">{}</a></li>'.format(
                index, base, title)

        toc_xhtml += '</ol>\n</nav>\n</body>\n</html>'

        return toc_xhtml.encode('utf-8')

    def tocncx_XML(self) -> bytes:
        # Returns the XML data for the TOC.ncx file

        toc_ncx = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" xml:lang="fr" version="2005-1">\n'
            '<head>\n</head>\n'
            '<navMap>\n'
        )

        for index, markdown in enumerate(self.markdowns):
            base = splitext(basename(markdown["markdown"]))[0]
            title = escape_xml(self.chapter_title(markdown["markdown"]))
            toc_ncx += (
                '<navPoint id="navpoint-{}">\n'.format(index) +
                '<navLabel>\n<text>{}</text>\n</navLabel>'.format(title) +
                '<content src="s{:05d}-{}.xhtml"/>'.format(index, base) +
                ' </navPoint>'
            )

        toc_ncx += '</navMap>\n</ncx>'

        return toc_ncx.encode('utf-8')

    def chapter_title(self, markdown_name: str) -> str:
        with open(self.get_path(markdown_name), "r", encoding="utf-8") as f:
            markdown_data = f.read()

        return sub(r'^#* *', '', markdown_data.split("\n")[0])

    def chapter_XML(self, markdown_name: str, styles: list[str]) -> bytes:
        # Returns the XML data for a given markdown chapter file, with the
        # corresponding css chapter files
        with open(self.get_path(markdown_name), "r", encoding="utf-8") as f:
            markdown_data = f.read()

        html_text = markdown(markdown_data,
                             extensions=["codehilite",
                                         "tables", "fenced_code"],
                             extension_configs={
                                 "codehilite": {"guess_lang": False}}
                             )

        all_xhtml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">\n'
            '<head>\n<meta http-equiv="default-style" content="text/html; charset=utf-8"/>\n'
        )

        for style in styles:
            all_xhtml += '<link rel="stylesheet" href="css/{}" type="text/css"/>\n'.format(
                style)

        all_xhtml += '</head>\n<body>\n' + html_text + '\n</body>\n</html>'

        return all_xhtml.encode('utf-8')

    def epub_put(self, epub: ZipFile, filename: str, data: str) -> None:
        epub.writestr(filename, data, ZIP_DEFLATED, 9)

    def create_epub(self, epub_path: str):
        with ZipFile(epub_path, "w") as epub:
            # First, write the mimetype
            self.epub_put(epub, "mimetype", "application/epub+zip")

            # Then, the file container.xml which just points to package.opf
            self.epub_put(epub, "META-INF/container.xml", self.container_XML())

            # Then, the package.opf file itself
            self.epub_put(epub, "OPS/package.opf", self.packageOPF_XML())

            # First, we create the cover page
            self.epub_put(epub, "OPS/titlepage.xhtml", self.coverpage_XML())

            # Now, we are going to convert the Markdown files to xhtml files
            for index, chapter in enumerate(self.settings_data["chapters"]):
                chapter_name = chapter["markdown"]
                chapter_styles = self.settings_data["default_css"][:]
                if 'css' in chapter:
                    chapter_styles.append(chapter["css"])

                chapter_data = self.chapter_XML(chapter_name, chapter_styles)
                self.epub_put(epub, "OPS/s{:05d}-{}.xhtml".format(index, splitext(basename(chapter_name))[0]),
                              chapter_data)

            # Writing the TOC.xhtml file
            self.epub_put(epub, "OPS/TOC.xhtml", self.toc_XML())

            # Writing the TOC.ncx file
            self.epub_put(epub, "OPS/toc.ncx", self.tocncx_XML())

            # Copy image files
            for _, image_name in enumerate(self.images):
                with open(self.get_path(image_name), "rb") as f:
                    self.epub_put(
                        epub, "OPS/images/{}".format(basename(image_name)), f.read())

            # Copy CSS files
            for _, style_name in enumerate(self.styles):
                with open(self.get_path(style_name), "rb") as f:
                    self.epub_put(
                        epub, "OPS/{}".format(style_name), f.read())


def main(arguments: list[str]):
    if len(arguments) < 2:
        print("\nUsage:")
        print("    python3 mark2epub.py <markdown_directory> <output.epub>")
        exit(1)

    epub_generator = EPubGenerator(arguments[0])
    epub_generator.create_epub(arguments[1])

    print("eBook creation complete")


if __name__ == "__main__":
    main(argv[1:])

#!/usr/bin/env python3
from os import listdir
from os.path import basename, splitext, abspath, join
from sys import argv, stderr
from markdown import markdown
from xml.dom.minidom import Document, DocumentFragment
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from json import load
from re import sub
from uuid import uuid4
from datetime import datetime
from PIL import Image
from io import BytesIO


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


def create(doc: Document, tag: str, attributes: dict, content=None) -> Document:
    element = doc.createElement(tag)
    for key, value in attributes.items():
        element.setAttribute(key, value)

    if content:
        if isinstance(content, DocumentFragment):
            element.appendChild(content)
        else:
            element.appendChild(doc.createTextNode(content))

    return element


class EPubGenerator:
    def __init__(self, source_directory: str) -> None:
        self.source_directory = abspath(source_directory)
        settings_path = self.get_path("description.json")

        self.uuid = 'm2e-' + str(uuid4())

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

    def find_images(self):
        extensions = [".gif", ".jpg", ".jpeg", ".png"]
        images = [join('images', basename(image)) for image in listdir(
            self.get_path('images')) if splitext(image)[1] in extensions]

        return images

    def _create_package(self, doc: Document) -> Document:
        return create(doc, "package", {
            "xmlns": "http://www.idpf.org/2007/opf",
            "version": "3.0",
            "xml:lang": "en",
            "unique-identifier": self.uuid
        })

    def _create_metadata(self, doc: Document) -> Document:
        metadata = create(doc, 'metadata',
                          {'xmlns:dc': 'http://purl.org/dc/elements/1.1/'})

        metadata_settings = self.settings_data["metadata"]

        ids = {
            "dc:title": "title",
            "dc:creator": "creator",
            "dc:identifier": self.uuid
        }

        for key, value in metadata_settings.items():
            if len(value) == 0:
                continue

            if key in ids:
                entry = create(doc, key, {'id': ids[key]}, value)
            else:
                entry = create(doc, key, {}, value)

            metadata.appendChild(entry)

        # Ensure compatibility by providing a modified meta tag in the metadata
        metadata.appendChild(create(doc, "meta", {
            "property": "dcterms:modified",
        }, datetime.now().strftime(r"%Y-%m-%dT%H:%M:%SZ")
        ))

        # Ensure compatibility by providing a cover meta tag in the metadata
        for index, image_name in enumerate(self.images):
            if image_name == self.settings_data["cover_image"]:
                metadata.appendChild(create(doc, 'meta', {
                    'name': "cover",
                    'content': f"image-{index:05d}"
                }))

        return metadata

    def _create_manifest(self, doc: Document) -> Document:
        manifest = doc.createElement('manifest')

        # TOC.xhtml file for EPUB 3
        manifest.appendChild(create(doc, 'item', {
            'id': "toc",
            'properties': "nav",
            'href': "TOC.xhtml",
            'media-type': "application/xhtml+xml"
        }))

        # Ensure retrocompatibility by also providing a TOC.ncx file
        manifest.appendChild(create(doc, 'item', {
            'id': "ncx",
            'href': "toc.ncx",
            'media-type': "application/x-dtbncx+xml"
        }))

        manifest.appendChild(create(doc, 'item', {
            'id': "titlepage",
            'href': "titlepage.xhtml",
            'media-type': "application/xhtml+xml"
        }))

        for index, markdown in enumerate(self.markdowns):
            base = splitext(basename(markdown['markdown']))[0]
            manifest.appendChild(create(doc, 'item', {
                'id': f"s{index:05d}",
                'href': f"s{index:05d}-{base}.xhtml",
                'media-type': "application/xhtml+xml"
            }))

        for index, image_name in enumerate(self.images):
            image = create(doc, 'item', {
                'id': f"image-{index:05d}",
                'href': image_name,
                'media-type': get_image_mimetype(image_name)
            })

            if image_name == self.settings_data["cover_image"]:
                image.setAttribute('properties', "cover-image")

            manifest.appendChild(image)

        for index, style_name in enumerate(self.styles):
            manifest.appendChild(create(doc, 'item', {
                'id': f"css-{index:05d}",
                'href': style_name,
                'media-type': "text/css"
            }))

        return manifest

    def _create_spine(self, doc: Document) -> Document:
        spine = create(doc, 'spine', {'toc': 'ncx'})

        spine.appendChild(create(doc, 'itemref', {
            'idref': "titlepage",
            'linear': "yes"
        }))

        for index, _ in enumerate(self.markdowns):
            spine.appendChild(create(doc, 'itemref', {
                'idref': f"s{index:05d}",
                'linear': "yes"
            }))

        return spine

    def _create_guide(self, doc: Document) -> Document:
        guide = doc.createElement('guide')
        guide.appendChild(create(doc, 'reference', {
            'type': 'cover',
            'title': 'Cover image',
            'href': 'titlepage.xhtml'
        }))

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
            '<container version="1.0"'
            ' xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles>'
            '<rootfile full-path="OPS/package.opf"'
            ' media-type="application/oebps-package+xml"/>'
            '</rootfiles></container>'
        ).encode('utf-8')

    def coverpage_XML(self) -> bytes:
        # Returns the XML data for the coverpage.xhtml file
        cover_image_path = self.settings_data["cover_image"]
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="fr">'
            '<head>'
            '<title>'
            f'{escape_xml(self.settings_data["metadata"]["dc:title"])}'
            '</title>'
            '</head>'
            '<body>'
            '<img'
            f' src="{cover_image_path}" style="height:100%;max-width:100%;"/>'
            '</body></html>'
        ).encode('utf-8')

    def toc_XML(self) -> bytes:
        # Returns the XML data for the TOC.xhtml file
        toc_xhtml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            ' xmlns:epub="http://www.idpf.org/2007/ops" lang="en">'
            '<head>'
            '<meta http-equiv="default-style"'
            ' content="text/html; charset=utf-8"/>'
            '<title>Contents</title>'
        )

        for style_name in self.default_styles:
            toc_xhtml += (
                f'<link rel="stylesheet" href="{style_name}" type="text/css"/>'
            )

        toc_xhtml += (
            '</head>'
            '<body>'
            '<nav epub:type="toc" role="doc-toc" id="toc">'
            '<h2>Contents</h2>'
            '<ol epub:type="list">'
        )

        for index, markdown in enumerate(self.markdowns):
            base = splitext(basename(markdown["markdown"]))[0]
            title = escape_xml(self.chapter_title(markdown["markdown"]))
            toc_xhtml += (
                '<li>'
                f'<a href="s{index:05d}-{base}.xhtml">{title}</a>'
                '</li>'
            )

        toc_xhtml += '</ol>\n</nav>\n</body>\n</html>'

        return toc_xhtml.encode('utf-8')

    def tocncx_XML(self) -> bytes:
        # Returns the XML data for the TOC.ncx file
        identifier = escape_xml(
            self.settings_data["metadata"]["dc:identifier"])
        title = escape_xml(self.settings_data["metadata"]["dc:title"])
        creator = escape_xml(self.settings_data["metadata"]["dc:creator"])
        toc_ncx = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"'
            ' xml:lang="fr" version="2005-1">'
            '<head>'
            f'<meta name="dtb:uid" content="{identifier}"/>'
            '<meta name="dtb:depth" content="1"/>'
            '<meta name="dtb:totalPageCount" content="0"/>'
            '<meta name="dtb:maxPageNumber" content="0"/>'
            '</head>'
            '<docTitle>'
            f'<text>{title}</text>'
            '</docTitle>'
            '<docAuthor>'
            f'<text>{creator}</text>'
            '</docAuthor>'
            '<navMap>'
        )

        for index, markdown in enumerate(self.markdowns):
            base = splitext(basename(markdown["markdown"]))[0]
            title = escape_xml(self.chapter_title(markdown["markdown"]))
            toc_ncx += (
                f'<navPoint id="navpoint-{index}">'
                f'<navLabel><text>{title}</text></navLabel>'
                f'<content src="s{index:05d}-{base}.xhtml"/>'
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
        title = self.chapter_title(markdown_name)

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
            '<html xmlns="http://www.w3.org/1999/xhtml"'
            ' xmlns:epub="http://www.idpf.org/2007/ops" lang="en">'
            '<head>'
            f'<title>{title}</title>'
            '<meta http-equiv="default-style"'
            ' content="text/html; charset=utf-8"/>'
        )

        for style in styles:
            all_xhtml += (
                f'<link rel="stylesheet" href="{style}" type="text/css"/>'
            )

        all_xhtml += f'</head><body>{html_text}</body></html>'

        return all_xhtml.encode('utf-8')

    def process_image(self, image_name: str, options: dict) -> bytes:
        image = Image.open(self.get_path(image_name))
        format = image.format

        # Remove EXIF data
        data = list(image.getdata())
        image = Image.new(image.mode, image.size)
        image.putdata(data)

        if options["gray-images"]:
            image = image.convert("L")

        output = BytesIO()
        if format == "JPEG":
            quality = int(options["jpeg-quality"])
            image.save(output, format, quality=quality)
        else:
            image.save(output, format)

        return output.getvalue()

    def epub_put(self, epub: ZipFile, filename: str, data: str) -> None:
        if filename == "mimetype":
            epub.writestr(filename, data, ZIP_STORED)
        else:
            epub.writestr(filename, data, ZIP_DEFLATED, 9)

    def create_epub(self, epub_path: str, options: dict):
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
                base = splitext(basename(chapter_name))[0]
                self.epub_put(
                    epub,
                    f"OPS/s{index:05d}-{base}.xhtml",
                    chapter_data
                )

            # Writing the TOC.xhtml file
            self.epub_put(epub, "OPS/TOC.xhtml", self.toc_XML())

            # Writing the TOC.ncx file
            self.epub_put(epub, "OPS/toc.ncx", self.tocncx_XML())

            # Copy image files
            for _, image_name in enumerate(self.images):
                processed = self.process_image(image_name, options)
                self.epub_put(epub, f"OPS/{image_name}", processed)

            # Copy CSS files
            for _, style_name in enumerate(self.styles):
                with open(self.get_path(style_name), "rb") as f:
                    self.epub_put(
                        epub, f"OPS/{style_name}", f.read())


OPTIONS = {
    "convert": {
        "usage": "convert <markdown_directory> <output.epub>",
        "description": "Convert a directory of markdown files into an EPUB",
        "settings": {
            "gray-images": {
                "default": False,
                "description": "Convert all images to grayscale"
            },
            "jpeg-quality": {
                "default": "95",
                "description": "Quality for JPEG images"
            }
        },
        "min_args": 2,
        "max_args": 2
    },
    "help": {
        "usage": "help",
        "description": "Display this help message",
        "settings": {},
        "min_args": 0,
        "max_args": 0
    },
}


def print_usage():
    print("\nUsage: mark2epub.py <command> [options] [arguments]")

    print("\nCommands:")
    for command, infos in OPTIONS.items():
        print(f"    {command}:")
        print(f"        usage: {infos['usage']}")
        print(f"        description: {infos['description']}")

        if len(infos['settings']) > 0:
            print("        settings:")
            for setting, settings in infos['settings'].items():
                print(f"            --{setting} - {settings['description']}"
                      f" (default: {settings['default']})")

        print()


def parse_command_line(arguments: list[str]) -> dict:
    command_line = {
        'command': None,
        'options': {},
        'arguments': []
    }

    end_of_options = False
    for argument in arguments:
        if not end_of_options:
            if argument == '--':
                end_of_options = True
                continue

            if argument.startswith("--"):
                parts = argument[2:].split("=", 1)
                key = parts[0]
                if len(parts) == 1:
                    value = True
                else:
                    value = parts[1]

                command_line['options'][key] = value
                continue

        if command_line['command'] is None:
            command_line['command'] = argument

            if argument in OPTIONS:
                for option in OPTIONS[argument]['settings']:
                    default = OPTIONS[argument]['settings'][option]['default']
                    command_line['options'][option] = default

            continue

        command_line['arguments'].append(argument)

    return command_line


def check_command_line(command_line: dict) -> None:
    if command_line['command'] is None:
        print_usage()
        print("ERROR: No command provided", file=stderr)
        exit(1)

    command = command_line['command']
    if command not in OPTIONS:
        print(f"ERROR: Unknown command '{command}'", file=stderr)
        exit(2)

    options = command_line['options']
    for option in options:
        if option not in OPTIONS[command]['settings']:
            print(
                f"ERROR: Unknown option {option} for command {command}",
                file=stderr
            )
            exit(3)

    min_args = OPTIONS[command]['min_args']
    max_args = OPTIONS[command]['max_args']
    arg_count = len(command_line['arguments'])
    if not (min_args <= arg_count <= max_args):
        if min_args == max_args:
            print(
                f"ERROR: Invalid arguments count, got {arg_count}"
                f" but expected {min_args}"
                f" for command {command}",
                file=stderr
            )
        else:
            print(
                f"ERROR: Invalid arguments count, got {arg_count}"
                f" but expected between {min_args} and {max_args})"
                f" for command {command}",
                file=stderr
            )
        exit(4)


def main(arguments: list[str]):
    command = parse_command_line(arguments)
    check_command_line(command)

    if command['command'] == "convert":
        epub_generator = EPubGenerator(command['arguments'][0])
        epub_generator.create_epub(command['arguments'][1], command['options'])

        print("SUCCESS: eBook creation complete")

    if command['command'] == "help":
        print_usage()


if __name__ == "__main__":
    main(argv[1:])

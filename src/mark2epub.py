#!/usr/bin/env python3
"""
This script converts a directory of markdown files into an EPUB file.
It provides functionality to customize the EPUB generation process by specifying
various settings.

Usage:
    python3 mark2epub.py convert <markdown_directory> <output.epub>
    python3 mark2epub.py init <new_directory>
    python3 mark2epub.py help

Options:
    convert             Convert a directory of markdown files into an EPUB
    init                Create and fill a directory
    help                Display this help message

Settings:
    --gray-images         Convert all images to grayscale
    --jpeg-quality        Quality for JPEG images
    --zopfli              Use Zopfli (advzip required) for compression

Examples:
    python mark2epub.py convert my_markdowns/ my_book.epub
    python mark2epub.py init new_book/
    python mark2epub.py help
"""

from os import listdir, unlink, mkdir
from os.path import basename, splitext, abspath, join
from sys import argv, exit as sys_exit
import sys
from xml.dom.minidom import Document, Node, Element, parseString
from xml.parsers.expat import ExpatError
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
from json import load, dumps
from re import sub
from uuid import uuid4
from datetime import datetime, date
from io import BytesIO
from shutil import which
from subprocess import run, PIPE
from tempfile import NamedTemporaryFile
from PIL import Image, ImageDraw
from markdown import markdown

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
            },
            "zopfli": {
                "default": False,
                "description": "Use Zopfli (advzip required) for compression"
            }
        },
        "min_args": 2,
        "max_args": 2
    },
    "init": {
        "usage": "init <new_directory>",
        "description": "Create and fill a directory",
        "settings": {},
        "min_args": 1,
        "max_args": 1
    },
    "help": {
        "usage": "help",
        "description": "Display this help message",
        "settings": {},
        "min_args": 0,
        "max_args": 0
    },
}

DEFAULT_STYLES = r"""
img {
    max-width: 100%;
    height: auto;      
}

img.cover {
    display: block;
    max-width: 100%;
    max-height: 100%;
    height: 100%;
    width: auto;
    margin-left: auto;
    margin-right: auto;
}

body.cover, html.cover {
    margin: 0;
    padding: 0;
    height: 100%;
    width: 100%;
    overflow: hidden;
}

table {
    border-collapse: collapse;
    width: 100%;
    font-size: 80%;
}

td, th {
    border: 2px solid #bbb;
    padding: 10px;
}

tr:nth-child(even) { background-color: #eee; }

th {
    padding-top: 1em;
    padding-bottom: 1em;
    text-align: left;
    background-color: #444;
    color: white;
    font-size: 80%;
}

blockquote {
    margin-left: 10%;
    font-style: italic;
}
"""

# Return codes
ERROR_NO_COMMAND = 1
ERROR_UNKNOWN_COMMAND = 2
ERROR_UNKNOWN_OPTION = 3
ERROR_ARGUMENT_COUNT = 4
ERROR_ZOPFLI_UNAVAILABLE = 5
ERROR_ZOPFLI = 6
ERROR_DIRECTORY_EXISTS = 7
ERROR_INVALID_MARKDOWN = 8


def fatal_error(message: str, exit_code: int) -> None:
    """Print an error message on stderr and exit the program."""
    print(f"ERROR: {message}", file=sys.stderr)
    sys_exit(exit_code)


def get_image_mimetype(image_name: str) -> str:
    """Return the mimetype of an image based on its name."""
    _, extension = splitext(image_name)

    if extension == ".gif":
        return "image/gif"

    if extension in (".jpg", ".jpeg"):
        return "image/jpeg"

    if extension == ".png":
        return "image/png"

    return "application/octet-stream"


def create(tag: str, attributes: dict = None, content=None) -> Element:
    """Create an XML element with the given tag, attributes and content."""
    doc = Document()
    element = doc.createElement(tag)

    if attributes is not None:
        for key, value in attributes.items():
            element.setAttribute(key, value)

    if content:
        if isinstance(content, Element):
            element.appendChild(content)
        else:
            element.appendChild(doc.createTextNode(content))

    return element


def append_to(doc: Node, tag: str, attributes: dict = None, content=None) -> Document:
    """Create an XML element and append it to the document."""
    element = create(tag, attributes, content)
    doc.appendChild(element)
    return element


class EPubGenerator:
    """Class to generate an EPUB file from a directory of markdown files."""

    def __init__(self, source_directory: str) -> None:
        self.source_directory = abspath(source_directory)
        settings_path = self.get_path("description.json")

        self.uuid = 'm2e-' + str(uuid4())

        with open(settings_path, "rb") as json_file:
            self.settings_data = load(json_file)

        self.markdowns = [chapter.copy()
                          for chapter in self.settings_data["chapters"]]

        self.language = self.settings_data["metadata"]["dc:language"]

        self.styles = set(self.settings_data["default_css"])
        self.styles.update([chapter["css"]
                           for chapter in self.markdowns if "css" in chapter])

        self.images = self.find_images()

    def get_path(self, relative_path: str) -> str:
        """Return the absolute path of a file in the source directory."""
        return join(self.source_directory, relative_path)

    def find_images(self):
        """Return a list of image files in the image directory."""
        extensions = [".gif", ".jpg", ".jpeg", ".png"]
        images = [join('images', basename(image)) for image in listdir(
            self.get_path('images')) if splitext(image)[1] in extensions]

        return images

    def _create_package(self) -> Document:
        """Create the package element of the OPF file."""
        return create("package", {
            "xmlns": "http://www.idpf.org/2007/opf",
            "version": "3.0",
            "xml:lang": self.language,
            "unique-identifier": self.uuid
        })

    def _create_metadata(self) -> Document:
        """Create the metadata element of the OPF file."""
        metadata = create('metadata',
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
                entry = create(key, {'id': ids[key]}, value)
            else:
                entry = create(key, {}, value)

            metadata.appendChild(entry)

        # Ensure compatibility by providing a modified meta tag in the metadata
        metadata.appendChild(create("meta", {
            "property": "dcterms:modified",
        }, datetime.now().strftime(r"%Y-%m-%dT%H:%M:%SZ")
        ))

        # Ensure compatibility by providing a cover meta tag in the metadata
        for index, image_name in enumerate(self.images):
            if image_name == self.settings_data["cover_image"]:
                metadata.appendChild(create('meta', {
                    'name': "cover",
                    'content': f"image-{index:05d}"
                }))

        return metadata

    def _create_manifest(self) -> Document:
        """Create the manifest element of the OPF file."""
        manifest = create('manifest')

        # TOC.xhtml file for EPUB 3
        append_to(manifest, 'item', {
            'id': "toc",
            'properties': "nav",
            'href': "TOC.xhtml",
            'media-type': "application/xhtml+xml"
        })

        # Ensure retrocompatibility by also providing a TOC.ncx file
        append_to(manifest, 'item', {
            'id': "ncx",
            'href': "toc.ncx",
            'media-type': "application/x-dtbncx+xml"
        })

        append_to(manifest, 'item', {
            'id': "titlepage",
            'href': "titlepage.xhtml",
            'media-type': "application/xhtml+xml"
        })

        for index, entry in enumerate(self.markdowns):
            base = splitext(basename(entry['markdown']))[0]
            append_to(manifest, 'item', {
                'id': f"s{index:05d}",
                'href': f"s{index:05d}-{base}.xhtml",
                'media-type': "application/xhtml+xml"
            })

        for index, image_name in enumerate(self.images):
            image = append_to(manifest, 'item', {
                'id': f"image-{index:05d}",
                'href': image_name,
                'media-type': get_image_mimetype(image_name)
            })

            if image_name == self.settings_data["cover_image"]:
                image.setAttribute('properties', "cover-image")

        for index, style_name in enumerate(self.styles):
            append_to(manifest, 'item', {
                'id': f"css-{index:05d}",
                'href': style_name,
                'media-type': "text/css"
            })

        return manifest

    def _create_spine(self) -> Document:
        """Create the spine element of the OPF file."""
        spine = create('spine', {'toc': 'ncx'})

        append_to(spine, 'itemref', {
            'idref': "titlepage",
            'linear': "yes"
        })

        for index, _ in enumerate(self.markdowns):
            append_to(spine, 'itemref', {
                'idref': f"s{index:05d}",
                'linear': "yes"
            })

        return spine

    def _create_guide(self) -> Document:
        """Create the guide element of the OPF file."""
        guide = create('guide')
        append_to(guide, 'reference', {
            'type': 'cover',
            'title': 'Cover image',
            'href': 'titlepage.xhtml'
        })

        return guide

    def package_opf_xml(self):
        """Return the XML data for the package.opf file."""
        opf = Document()

        package = self._create_package()

        package.appendChild(self._create_metadata())
        package.appendChild(self._create_manifest())
        package.appendChild(self._create_spine())
        package.appendChild(self._create_guide())

        opf.appendChild(package)

        return opf.toprettyxml()

    def container_xml(self) -> bytes:
        """Return the XML data for the container.xml file."""
        doc = Document()
        container = create('container', {
            'version': "1.0",
            'xmlns': "urn:oasis:names:tc:opendocument:xmlns:container"
        })

        rootfiles = create('rootfiles', {})
        rootfile = create('rootfile', {
            'full-path': "OPS/package.opf",
            'media-type': "application/oebps-package+xml"
        })

        rootfiles.appendChild(rootfile)
        container.appendChild(rootfiles)
        doc.appendChild(container)

        return doc.toxml(encoding="utf-8")

    def coverpage_xml(self) -> bytes:
        """Return the XML data for the coverpage.xhtml file."""
        cover_image_path = self.settings_data["cover_image"]

        doc = Document()

        html = append_to(doc, 'html', {
            'xmlns': "http://www.w3.org/1999/xhtml",
            'xml:lang': self.language
        })

        head = append_to(html, 'head', {})

        append_to(head, 'title',
                  {},
                  self.settings_data["metadata"]["dc:title"]
                  )

        for style_name in self.styles:
            append_to(head, 'link', {
                'rel': "stylesheet",
                'href': style_name,
                'type': "text/css"
            })

        body = append_to(html, 'body', {
            "class": "cover"
        })

        append_to(body, 'img', {
            "src": cover_image_path,
            "class": "cover"
        })

        return doc.toxml(encoding="utf-8")

    def toc_xml(self) -> bytes:
        """Returns the XML data for the TOC.xhtml file."""
        doc = Document()

        html = append_to(doc, 'html', {
            'xmlns': "http://www.w3.org/1999/xhtml",
            'xmlns:epub': "http://www.idpf.org/2007/ops",
            'xml:lang': self.language
        })

        head = append_to(html, 'head')

        append_to(head, 'meta', {
            'http-equiv': "default-style",
            'content': "text/html; charset=utf-8"
        })

        append_to(head, 'title', {}, "Contents")

        for style_name in self.settings_data["default_css"]:
            append_to(head, 'link', {
                'rel': "stylesheet",
                'href': style_name,
                'type': "text/css"
            })

        body = append_to(html, 'body')
        nav = append_to(body, 'nav', {
            'epub:type': "toc",
            'role': "doc-toc",
            'id': "toc"
        })

        append_to(nav, 'h2', {}, "Contents")

        nav_list = append_to(nav, 'ol', {
            'epub:type': "list"
        })

        for index, entry in enumerate(self.markdowns):
            base = splitext(basename(entry["markdown"]))[0]
            title = self.chapter_title(entry["markdown"])
            nav_item = append_to(nav_list, 'li')
            append_to(nav_item, 'a', {
                'href': f"s{index:05d}-{base}.xhtml"
            }, title)

        return doc.toxml(encoding="utf-8")

    def tocncx_xml(self) -> bytes:
        """Returns the XML data for the TOC.ncx file."""
        identifier = self.settings_data["metadata"]["dc:identifier"]

        title = self.settings_data["metadata"]["dc:title"]
        creator = self.settings_data["metadata"]["dc:creator"]

        doc = Document()

        ncx = append_to(doc, 'ncx', {
            'xmlns': "http://www.daisy.org/z3986/2005/ncx/",
            'xml:lang': self.language,
            'version': "2005-1"
        })

        head = append_to(ncx, 'head')

        append_to(head, 'meta', {'name': "dtb:uid", 'content': identifier})
        append_to(head, 'meta', {'name': "dtb:depth", 'content': "1"})
        append_to(head, 'meta', {'name': "dtb:totalPageCount", 'content': "0"})
        append_to(head, 'meta', {'name': "dtb:maxPageNumber", 'content': "0"})

        doc_title = append_to(ncx, 'docTitle')
        append_to(doc_title, 'text', {}, title)
        doc_author = append_to(ncx, 'docAuthor')
        append_to(doc_author, 'text', {}, creator)

        nav_map = append_to(ncx, 'navMap')

        for index, entry in enumerate(self.markdowns):
            base = splitext(basename(entry["markdown"]))[0]
            title = self.chapter_title(entry["markdown"])

            nav_point = append_to(nav_map, 'navPoint', {
                'id': f"navpoint-{index}",
            })

            nav_label = append_to(nav_point, 'navLabel')
            append_to(nav_label, 'text', {}, title)
            append_to(nav_point, 'content', {
                'src': f"s{index:05d}-{base}.xhtml"
            })

        return doc.toxml(encoding="utf-8")

    def chapter_title(self, markdown_name: str) -> str:
        """Returns the title of a chapter from its markdown file."""
        with open(self.get_path(markdown_name), "r", encoding="utf-8") as chap:
            markdown_data = chap.read()

        return sub(r'^#* *', '', markdown_data.split("\n")[0])

    def chapter_xml(self, markdown_name: str, styles: list[str]) -> bytes:
        """
        Returns the XML data for a given markdown chapter file, with the
        corresponding css chapter files
        """
        with open(self.get_path(markdown_name), "r", encoding="utf-8") as chap:
            markdown_data = chap.read()

        html_text = markdown(
            markdown_data,
            extensions=["codehilite", "tables", "fenced_code"],
            extension_configs={"codehilite": {"guess_lang": False}},
            output_format="xhtml"
        )

        xml_before = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            '<body>'
        )
        xml_after = '</body></html>'
        try:
            body_content = parseString(xml_before + html_text + xml_after)
        except ExpatError:
            fatal_error(
                f'Invalid markdown file {markdown_name}',
                ERROR_INVALID_MARKDOWN
            )

        doc = Document()

        html = append_to(doc, 'html', {
            'xmlns': "http://www.w3.org/1999/xhtml",
            'xmlns:epub': "http://www.idpf.org/2007/ops",
            'xml:lang': self.language
        })

        head = append_to(html, 'head')
        append_to(head, 'title', {}, self.chapter_title(markdown_name))
        append_to(head, 'meta', {
            'http-equiv': "default-style",
            'content': "text/html; charset=utf-8"
        })

        for style in styles:
            append_to(head, 'link', {
                'rel': "stylesheet",
                'href': style,
                'type': "text/css"
            })

        body = append_to(html, 'body')
        for element in body_content.getElementsByTagName("body")[0].childNodes:
            body.appendChild(element)

        return doc.toxml(encoding="utf-8")

    def process_image(self, image_name: str, options: dict) -> bytes:
        """Process an image file and return its binary data."""
        image = Image.open(self.get_path(image_name))
        img_format = image.format

        # Remove EXIF data
        data = list(image.getdata())
        image = Image.new(image.mode, image.size)
        image.putdata(data)

        if options["gray-images"]:
            image = image.convert("L")

        output = BytesIO()
        if img_format == "JPEG":
            quality = int(options["jpeg-quality"])
            image.save(output, img_format, quality=quality, optimize=True)
            return output.getvalue()

        if img_format == "PNG" and options["zopfli"]:
            image.save(output, img_format, optimize=True)

            with NamedTemporaryFile() as png_temp:
                png_temp.write(output.getvalue())
                result = run(
                    [
                        'zopflipng',
                        '-y',
                        '--iterations=63',
                        '--lossy_transparent',
                        '--lossy_8bit',
                        '--filters=e',
                        png_temp.name,
                        png_temp.name + ".zopfli"
                    ],
                    stdout=PIPE,
                    stderr=PIPE,
                    check=False
                )

                if result.returncode != 0:
                    fatal_error(
                        f"Could not use zopflipng on {image_name}",
                        ERROR_ZOPFLI
                    )

            with open(png_temp.name + ".zopfli", "rb") as output_file:
                output = output_file.read()

            unlink(png_temp.name + ".zopfli")
            return output

        image.save(output, img_format, optimize=True)
        return output.getvalue()

    def epub_put(self, epub: ZipFile, filename: str, data: str) -> None:
        """Write a file to the EPUB archive."""
        if filename == "mimetype":
            epub.writestr(filename, data, ZIP_STORED)
        else:
            epub.writestr(filename, data, ZIP_DEFLATED, 9)

    def create_epub(self, epub_path: str, options: dict):
        """Create the EPUB file."""
        with ZipFile(epub_path, "w") as epub:
            # First, write the mimetype
            self.epub_put(epub, "mimetype", "application/epub+zip")

            # Then, the file container.xml which just points to package.opf
            self.epub_put(epub, "META-INF/container.xml", self.container_xml())

            # Then, the package.opf file itself
            self.epub_put(epub, "OPS/package.opf", self.package_opf_xml())

            # First, we create the cover page
            self.epub_put(epub, "OPS/titlepage.xhtml", self.coverpage_xml())

            # Now, we are going to convert the Markdown files to xhtml files
            for index, chapter in enumerate(self.settings_data["chapters"]):
                chapter_name = chapter["markdown"]
                chapter_styles = self.settings_data["default_css"][:]
                if 'css' in chapter:
                    chapter_styles.append(chapter["css"])

                chapter_data = self.chapter_xml(chapter_name, chapter_styles)
                base = splitext(basename(chapter_name))[0]
                self.epub_put(
                    epub,
                    f"OPS/s{index:05d}-{base}.xhtml",
                    chapter_data
                )

            # Writing the TOC.xhtml file
            self.epub_put(epub, "OPS/TOC.xhtml", self.toc_xml())

            # Writing the TOC.ncx file
            self.epub_put(epub, "OPS/toc.ncx", self.tocncx_xml())

            # Copy image files
            for _, image_name in enumerate(self.images):
                processed = self.process_image(image_name, options)
                self.epub_put(epub, f"OPS/{image_name}", processed)

            # Copy CSS files
            for _, style_name in enumerate(self.styles):
                with open(self.get_path(style_name), "rb") as style_file:
                    self.epub_put(
                        epub, f"OPS/{style_name}", style_file.read())


def create_template(template_directory: str) -> None:
    """Create a template directory with a description.json file."""
    # Create the template directory.
    try:
        mkdir(template_directory)
    except FileExistsError:
        fatal_error(
            f"{template_directory} already exists",
            ERROR_DIRECTORY_EXISTS
        )

    # Fill images directory.
    images_directory = join(template_directory, "images")
    mkdir(images_directory)

    cover = Image.new(mode="RGB", size=(800, 1000), color="blue")
    draw = ImageDraw.Draw(cover)
    draw.rectangle([(0, 460), (800, 540)], fill="yellow")
    cover.save(join(images_directory, "cover.jpg"))

    # Fill css directory.
    styles_directory = join(template_directory, "css")
    mkdir(styles_directory)

    with open(join(styles_directory, "general.css"), "wb") as general_css:
        general_css.write(DEFAULT_STYLES.encode("utf-8"))

    with open(join(styles_directory, "specific.css"), "wb") as specific_css:
        specific_css.write(
            "/* Specific CSS for a chapter */\n\n".encode("utf-8")
        )

    # Create the description.json file.
    description = {
        "metadata": {
            "dc:title": "The name of this document",
            "dc:creator": "Who has made this document?",
            "dc:language": "en-US",
            "dc:identifier": "An unambiguous reference to this document",
            "dc:source": "A work from which this document is derived",
            "meta": "",
            "dc:date": date.today().strftime(r"%Y-%m-%d"),
            "dc:publisher": "Who has made this document available?",
            "dc:contributor": "Who has made contributions to this document?",
            "dc:rights": "Rights held in and over the resource",
            "dc:description": "An account of this document",
            "dc:subject": "The topic of this document"
        },
        "cover_image": "images/cover.jpg",
        "default_css": [
            "css/general.css"
        ],
        "chapters": [
            {
                "markdown": "chapter1.md"
            },
            {
                "markdown": "chapter2.md",
                "css": "css/specific.css"
            }
        ]
    }

    description_name = join(template_directory, "description.json")
    with open(description_name, "wb") as description_file:
        description_file.write(
            dumps(description, indent=4).encode("utf-8")
        )

    # Create the chapter1.md file.
    with open(join(template_directory, "chapter1.md"), "wb") as chap1:
        chap1.write(
            '# Chapter 1\n\nThis is the first chapter.'.encode("utf-8")
        )

    # Create the chapter2.md file.
    with open(join(template_directory, "chapter2.md"), "wb") as chap2:
        chap2.write(
            '# Chapter 2\n\nThis is the second chapter.'.encode("utf-8")
        )


def print_usage():
    """Print the usage message."""
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
    """
    Parse the command line and return a dictionary with the command and its
    options and arguments.
    """
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
    """Check if the command line is valid."""
    if command_line['command'] is None:
        print_usage()
        fatal_error("No command provided", ERROR_NO_COMMAND)

    command = command_line['command']
    if command not in OPTIONS:
        fatal_error(f"Unknown command '{command}'", ERROR_UNKNOWN_COMMAND)

    options = command_line['options']
    for option in options:
        if option not in OPTIONS[command]['settings']:
            fatal_error(
                f"Unknown option {option} for command {command}",
                ERROR_UNKNOWN_OPTION
            )

    min_args = OPTIONS[command]['min_args']
    max_args = OPTIONS[command]['max_args']
    arg_count = len(command_line['arguments'])
    if not min_args <= arg_count <= max_args:
        if min_args == max_args:
            fatal_error(
                f"Invalid arguments count, got {arg_count}"
                f" but expected {min_args}"
                f" for command {command}",
                ERROR_ARGUMENT_COUNT
            )
        else:
            fatal_error(
                f"Invalid arguments count, got {arg_count}"
                f" but expected between {min_args} and {max_args})"
                f" for command {command}",
                ERROR_ARGUMENT_COUNT
            )


def main(arguments: list[str]):
    """Main function of the script."""
    command = parse_command_line(arguments)
    check_command_line(command)

    if command['command'] == "convert":
        source_directory = command['arguments'][0]
        output_epub = command['arguments'][1]
        options = command['options']

        # Check if advzip is available if Zopfli is requested before doing
        # anything
        use_zopfli = options['zopfli']
        if use_zopfli and which("advzip") is None:
            fatal_error(
                "advzip is required for Zopfli compression",
                ERROR_ZOPFLI_UNAVAILABLE
            )

        if use_zopfli and which("zopflipng") is None:
            fatal_error(
                "zopflipng is required for Zopfli compression",
                ERROR_ZOPFLI_UNAVAILABLE
            )

        epub_generator = EPubGenerator(source_directory)
        epub_generator.create_epub(output_epub, options)

        if use_zopfli:
            run(
                [
                    "advzip",
                    "--recompress",
                    "--shrink-insane",
                    "--iter=127",
                    "--pedantic",
                    "--quiet",
                    "--",
                    output_epub,
                ],
                check=False
            )

        print("SUCCESS: eBook creation complete")

    if command['command'] == "help":
        print_usage()

    if command['command'] == "init":
        template_directory = command['arguments'][0]
        create_template(template_directory)
        print(f"SUCCESS: {template_directory} template created")


if __name__ == "__main__":
    main(argv[1:])

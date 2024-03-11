from unittest import TestCase, main
from mock import patch
from os import devnull
from parameterized import parameterized
from mark2epub import (
    get_image_mimetype, create, append_to, parse_command_line,
    check_command_line, ERROR_NO_COMMAND, ERROR_UNKNOWN_COMMAND,
    ERROR_UNKNOWN_OPTION, ERROR_ARGUMENT_COUNT, ERROR_ZOPFLI_UNAVAILABLE,
    ERROR_ZOPFLI, ERROR_DIRECTORY_EXISTS
)

VOID = open(devnull, 'w')


class TestMark2Epub(TestCase):
    @parameterized.expand([
        ["png", "example/toto.png", "image/png"],
        ["jpg", "example/toto.jpg", "image/jpeg"],
        ["jpeg", "example/toto.jpeg", "image/jpeg"],
        ["empty", "", "application/octet-stream"],
        ["gif", "example/toto.gif", "image/gif"],
        ["gifjpeg", "example/toto.gif.jpeg", "image/jpeg"],
        ["noextension", "example.example/toto", "application/octet-stream"],
    ])
    def test_get_image_mimetype(self, _name, filepath, expected):
        self.assertEqual(get_image_mimetype(filepath), expected)

    @parameterized.expand([
        ["onlytag", "body", None, None, "<body/>"],
        ["attrs1", "p", {"class": "left"}, None, '<p class="left"/>'],
        ["attrs2", "p", {"class": "left"}, "", '<p class="left"/>'],
        ["attrs3", "p", {"class": "left", "id": "x"},
            None, '<p class="left" id="x"/>'],
        ["content", "p", None, "Hello", '<p>Hello</p>'],
        ["attrscontent", "p", {"class": "left"},
            "Hello", '<p class="left">Hello</p>'],
    ])
    def test_create(self, _name, tag, attributes, content, expected):
        self.assertEqual(
            create(tag, attributes, content).toxml(),
            expected
        )

    @parameterized.expand([
        ["onlytag", "body", None, None, '<html><body/></html>'],
        ["attrs1", "p", {"class": "left"}, None,
            '<html><p class="left"/></html>'],
        ["attrs2", "p", {"class": "left"}, "",
            '<html><p class="left"/></html>'],
        ["attrs3", "p", {"class": "left", "id": "x"},
            None, '<html><p class="left" id="x"/></html>'],
        ["content", "p", None, "Hello", '<html><p>Hello</p></html>'],
        ["attrscontent", "p", {"class": "left"},
            "Hello", '<html><p class="left">Hello</p></html>'],
    ])
    def test_append_to(self, _name, tag, attributes, content, expected):
        parent = create("html", None, None)
        append_to(parent, tag, attributes, content)
        self.assertEqual(
            parent.toxml(),
            expected
        )

    @parameterized.expand([
        ["noargs", [], {'command': None, 'options': {}, 'arguments': []}],
        ["command", ["command"], {'command': "command",
                                  'options': {}, 'arguments': []}],
        ["onlyopt", ["--opt"], {'command': None,
                                'options': {"opt": True}, 'arguments': []}],
        ["cmdopt", ["command", "--opt"],
         {'command': "command",
          'options': {"opt": True}, 'arguments': []}],
        ["optcmd", ["--opt", "command"],
         {'command': "command",
          'options': {"opt": True}, 'arguments': []}],
        ["optcmdarg", ["--opt", "command", "arg1", "arg2"],
         {'command': "command",
          'options': {"opt": True}, 'arguments': ["arg1", "arg2"]}],
        ["nooptcmdarg1", ["--", "--opt", "command", "arg1", "arg2"],
         {'command': "--opt",
          'options': {}, 'arguments': ["command", "arg1", "arg2"]}],
        ["nooptcmdarg2", ["--opt", "command", "--", "--arg1", "arg2"],
         {'command': "command",
          'options': {"opt": True}, 'arguments': ["--arg1", "arg2"]}],
        ["opt", ["--", "--", "--"],
         {'command': '--', 'options': {}, 'arguments': ['--']}],
        ["default", ["convert"],
         {'command': 'convert',
          'options': {
              "gray-images": False, "jpeg-quality": "95", "zopfli": False
          }, 'arguments': []}]
    ])
    def test_parse_command_line(self, _name, arguments, expected):
        self.assertEqual(parse_command_line(arguments), expected)

    @parameterized.expand([
        ["empty",
         {'command': None, 'options': {}, 'arguments': []},
         ERROR_NO_COMMAND],
        ["unknowncmd",
         {'command': "dummy", 'options': {}, 'arguments': []},
         ERROR_UNKNOWN_COMMAND],
        ["unknownopt",
         {'command': "help", 'options': {"dummy": True}, 'arguments': []},
         ERROR_UNKNOWN_OPTION],
        ["invalidarg",
         {'command': "help", 'options': {}, 'arguments': ["dummy"]},
         ERROR_ARGUMENT_COUNT],
    ])
    def test_invalid_check_command_line(self, _name, command_line, error_code):
        with patch('sys.stdout', VOID):
            with patch('sys.stderr', VOID):
                with self.assertRaises(SystemExit) as context:
                    check_command_line(command_line)
                self.assertEqual(context.exception.code, error_code)


if __name__ == '__main__':
    main()

def pytest_addoption(parser):
    parser.addoption(
        "--include-exploratory",
        action="store_true",
        default=False,
        help="Include execution cases under tests/cases/more (stash remains excluded).",
    )

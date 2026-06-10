# Notes

Note for other dev tasks etc.


## Publishing

Build:

```sh
rm -rf dist/
uv build
```

Check the build:

```sh
tar -tzf dist/*.tar.gz | head -50
unzip -l dist/*.whl
```

Setup:

```sh
uv tool install keyring

# set TEST Pypi token
keyring set https://test.pypi.org/legacy/ __token__
# paste token when prompted

# set Pypi token
keyring set https://upload.pypi.org/legacy/ __token__
# paste token when prompted
```

Test:

```sh
uv publish --publish-url https://test.pypi.org/legacy/ \
  --username __token__ --keyring-provider subprocess

# clean insall
uv run --with nsw-property-sales-data --index https://test.pypi.org/simple/ python -c "import nsw_property_sales_data"

# or if there are issues with 
uv run --with nsw-property-sales-data --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match python -c "import nsw_property_sales_data"
```

Publish:

```sh
uv publish --username __token__ --keyring-provider subprocess
```


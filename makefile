build:
	uv build

publish_test:
	source .env; UV_PUBLISH_TOKEN="${PYPI_TEST_TOKEN}" uv publish --index testpypi
	uv run --index testpypi --with isssm --no-project -- python -c "import isssm; print(isssm.__version__)"
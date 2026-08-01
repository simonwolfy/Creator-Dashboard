# Development Workflow

1. Branch from `develop` using `feature/<name>`.
2. Keep changes focused and update tests and documentation.
3. Open a pull request into `develop`.
4. Allow GitHub Actions to run the test suite.
5. Merge after validation.
6. Promote tested milestones from `develop` into `main` through a release pull request.

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pytest
python -m pytest
python -m creator_intelligence
```

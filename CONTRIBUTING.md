# Contributing to Paint a plate

Contributions are welcome: a fix, a feature, a test or a clearer sentence. Each one arrives as a pull request from your fork, tested by CI (GitHub Actions) and described in a few lines.

## 1. Fork and branch

1. Fork [AInVFX/ainvfx-paintaplate](https://github.com/AInVFX/ainvfx-paintaplate) on GitHub.
2. In your fork, open the **Actions** tab and enable the workflows if GitHub asks. CI then runs the tests on each push to your fork.
3. Clone your fork into ComfyUI's `custom_nodes` folder, and make a branch from `dev`:

   ```sh
   git clone https://github.com/<your-account>/ainvfx-paintaplate
   cd ainvfx-paintaplate
   git checkout -b my-change origin/dev
   ```

## 2. Make the change

[ARCHITECTURE.md](ARCHITECTURE.md) explains how the pack works, and [its section 12](ARCHITECTURE.md#12-how-to-make-common-changes) how to make common changes. Keep one change per pull request, with the test that proves it. [`tools/build_workflows.py`](tools/build_workflows.py) writes the workflows in `web/workflows`: change the script and run it, rather than a workflow's JSON.

## 3. Run the tests

[TESTING.md](TESTING.md) describes every test and how to run it, including [the page against the mock ComfyUI](TESTING.md#the-page-against-the-mock-comfyui). A change to what a model makes also needs a run [on a GPU machine](TESTING.md#on-a-gpu-machine).

## 4. Push, and let CI run

Push your branch to your fork. [CI](TESTING.md#ci) runs three jobs on each push: the unit tests, the page tests in four shards, and the live tests with ComfyUI on a CPU. They need no GPU and no secret. A green run on your fork shows that your change passes the same tests as the project.

## 5. Open a pull request

Open a pull request from your branch to `dev`. Its template asks for three things:

- **What changes**: what the page, a node or a file does now.
- **Why**: the problem it solves, or the issue it closes.
- **How it was tested**: the tests you ran, the link to CI's run on your fork, and a screenshot when the page changes.

GitHub holds CI's first run on a pull request from a new contributor until a maintainer approves it. A maintainer then reviews the change.

By contributing, you agree that your contribution is under the [Apache 2.0 licence](LICENSE), as the rest of the code.

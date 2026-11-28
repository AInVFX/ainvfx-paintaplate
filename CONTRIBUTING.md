# Contributing to Paint a plate

Contributions are welcome: a fix, a feature, a test or improved documentation. Open a pull request from your fork. CI (GitHub Actions) tests it. Then describe what it changes, why, and how you tested it.

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

Read [ARCHITECTURE.md](ARCHITECTURE.md) for how the pack works, and [its section 12](ARCHITECTURE.md#12-how-to-make-common-changes) for common changes. Make one change per pull request, with the test that proves it. To change a workflow in `web/workflows`, change [`tools/build_workflows.py`](tools/build_workflows.py) and run it: the script writes every workflow.

## 3. Run the tests

Run the tests as [TESTING.md](TESTING.md) describes, including [the page against the mock ComfyUI](TESTING.md#the-page-against-the-mock-comfyui). For a change to what a model makes, also run the tests [on a GPU machine](TESTING.md#on-a-gpu-machine).

## 4. Push, and let CI run

Push your branch to your fork. [CI](TESTING.md#ci) runs three jobs on each push: the unit tests, the page tests in seven shards, and the live tests with ComfyUI on a CPU. They need no GPU and no secret. When the three jobs pass on your fork, your change passes the same tests as the project.

## 5. Open a pull request

Open a pull request from your branch to `dev`. Its template asks for three things:

- **What changes**: what the page, a node or a file does now.
- **Why**: the problem it solves, or the issue it closes.
- **How it was tested**: the tests you ran, the link to CI's run on your fork, and a screenshot when the page changes.

For a new contributor, a maintainer approves CI's first run on the pull request, as GitHub asks. A maintainer then reviews the change.

By contributing, you agree that your contribution is under the [Apache 2.0 licence](LICENSE), as the rest of the code.

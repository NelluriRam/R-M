# Merge Conflict Resolution Guide

When the editor shows options like **Accept Current** and **Accept Incoming**, pick based on which version you want to keep after reviewing the conflicting blocks:

- **Current Change** = content that already exists on your branch (what you had before pulling/merging).
- **Incoming Change** = content from the branch you are merging in (e.g., `main` or a PR you pulled).

Recommended flow for this repository:

1. Open the conflicted file and read both versions around the conflict markers to understand what each side is doing.
2. If the incoming change contains the update you need (for example, a newer dashboard flow in `app.py` or dependency pinning in `requirements.txt`), choose **Accept Incoming**.
3. If your local change is the one you want to preserve, choose **Accept Current**.
4. If both parts are needed, choose **Accept Both** (or manually edit the file) and then clean up the combined result.
5. After resolving all conflicts, run a quick syntax check:
   - `python -m compileall app.py k8s_client.py monitoring.py ai_support.py`
6. Commit the resolved files and continue the merge or push your branch.

Tip: For `ui_mock.html`, prefer **Accept Incoming** when you want the latest mock UI flow; choose **Accept Current** if you only need your existing preview. You can also manually merge to keep specific sections from each.

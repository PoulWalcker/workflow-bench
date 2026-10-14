# SimsApp accessibility tree templates

Accessibility-tree snapshots captured with Blindly from a real messenger app,
renamed to SimsApp, with fictional English content. The snapshots preserve the
captured hierarchy, child order, roles, paths and geometry.

- `trees/`: seven complete tree snapshots.
- `fragments/`: twelve reusable subtrees extracted from the snapshots.
- `observations/`: twenty-one inspection and action-result records.
- `manifest.json`: file inventory, states, transitions, fragment pointers,
  provenance labels and SHA-256 digests.

Content digests use JSON serialized with sorted keys and compact separators.
Structural digests retain the source package's structural normalization.
Observed, reconstructed and unknown behavior is distinguished in the manifest;
these snapshots alone do not establish runtime behavior.

# Extract E2E archive fixture

`multipart.part*.rar` is a small encrypted multipart RAR fixture used by the
Utility Extract end-to-end test. Its test-only password is `pass-file-secret`;
the test supplies it through a temporary `.pass` file. The archive contains a
64 KiB deterministic `large.bin` payload generated with Python's
`random.Random(20261114).randbytes(64 * 1024)`.

The fixture is checked in so CI only needs RAR extraction support (`unar`), not
the proprietary RAR creation utility. Tests copy it into a temporary
Workspace-like directory and never extract into repository files.

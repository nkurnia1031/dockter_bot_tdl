# Extract E2E archive fixture

`rar3-sample.rar` is a tiny RAR3 fixture used by the Utility Extract
end-to-end test. It contains `testfile.jpg` (220 bytes) and `testfile.png`
(87 bytes). The fixture is from
[`ssokolow/rar-test-files`](https://github.com/ssokolow/rar-test-files) and is
dedicated to the public domain under CC0 1.0; see `LICENSE.cc0`.

RAR3 is used because the previous fixture used a newer RAR compression method
that 7-Zip does not support. CI installs the 7-Zip RAR module (`p7zip-rar`);
tests copy the fixture into a temporary Workspace-like directory and never
extract into repository files.

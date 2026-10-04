# Packaged CUDA/NVENC, real local GPU

October 4, 2026. Account-free, network-disabled checks on the local NVIDIA GeForce
RTX 4070 Ti, Windows driver 595.79. Both exact current runtime candidates pass:

| Candidate | Local image ID | Evidence |
| --- | --- | --- |
| Compute | sha256:d6bf574a817a0d38f0a33c930249f44472b7ec5108a4cf1b9c7b9840e2157688 | [Receipt](qualification/compute-encoder-gpu-local-20261004.json) |
| Instant | sha256:acddbe8e16b17ae1f84dfebaa5d85952bebe5c2ca0e45ce758a70887599bb2c7 | [Receipt](qualification/instant-encoder-gpu-local-20261004.json) |

The image source label is `5ac9167`. The probe loads the image's own
`/opt/gstreamer/gst-env`, GStreamer 1.24.6 and packaged `nvcudah264enc`. It generates
sixty 1280×720 frames at a declared 30 fps, uploads RGBx to CUDA memory, converts
to NV12 on CUDA, hardware-encodes H.264, parses it and decodes through packaged
`nvh264dec`. Sixty encoded and sixty decoded buffers complete; all sixty decoded
frames have distinct hashes. The fixture runs as UID/GID 1000, reads only its
public test script and removes its exact owned container. It uses no store account
or image/driver install and exports no profile/vendor log.

An initial probe assumed an unavailable `avdec_h264`. A fallback OpenH264 decoder
returned thirty decoded frames and was rejected. NVIDIA decoding passes all sixty.
A probe-construction syntax error was also corrected; the runner now compiles the
embedded program before creating a fixture. Earlier attempts and their cleanup
receipts remain in ignored test-results. The final Instant receipt pins the full
maintained harness; both receipts pin the identical synthetic pipeline program.

## Remaining graphics boundary

This proves the packaged CUDA memory upload/conversion and H.264 encode/decode
path. It is not compositor capture, actual negotiated stream resolution/rate,
WebRTC, sound, input, gameplay or Shared isolation acceptance.

The production `waylanddisplaysrc` plugin still fails initialization locally on
the missing `cuGraphicsEGLRegisterImage` symbol. Its failure is retained in the
synthetic pipeline logs; the independent encoder probe does not use that plugin.
The plugin scanner also reports its unavailable Python plugin dependency; this
probe uses GI and no Python GStreamer element. Neither warning is suppressed.

[NVIDIA's WSL guide](https://docs.nvidia.com/cuda/wsl-user-guide/index.html#features-not-yet-supported)
lists graphics/CUDA interoperability limitations. The observed missing EGL
registration function is consistent with that documented limitation. Full
capture acceptance needs the qualified native Linux graphics stack; this check
cannot establish it on Docker Desktop/WSL. Owner engine, driver and settings are
unchanged. No publication, production change or paid resource.

#!/bin/sh
# Build the minimal FFmpeg the Windows release uses, with only what Tello Revived needs:
# H.264 decoding, UDP input, saving mp4 and scaling frames (about 6 MB instead of about 65 MB).
#
#     tools/build_ffmpeg.sh 9.0.2 build/ffmpeg-slim
#     uv run python tools/build.py --slim-ffmpeg build/ffmpeg-slim
#
# The version must be the one PyAV was built with (python -c "import av; print(av.ffmpeg_version_info)").
# Run it in an MSYS2 UCRT64 shell, or Git Bash with a MinGW gcc, nasm and make on PATH.
set -eu
VERSION=$1
mkdir -p "$2"
OUT=$(cd "$2" && pwd)
WORK=$(pwd)/build/ffmpeg-$VERSION
mkdir -p "$WORK/tmp"
export TMPDIR="$WORK/tmp"  # configure needs a Unix-style temp folder
cd "$WORK"
[ -f "ffmpeg-$VERSION.tar.xz" ] || curl -sSfL -o "ffmpeg-$VERSION.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
rm -rf "ffmpeg-$VERSION"
tar -xf "ffmpeg-$VERSION.tar.xz"
cd "ffmpeg-$VERSION"
./configure --prefix="$WORK/install" --target-os=mingw32 --arch=x86_64 \
    --enable-shared --disable-static --disable-programs --disable-doc --disable-debug \
    --disable-autodetect --enable-w32threads --disable-everything \
    --enable-decoder=h264 --enable-parser=h264 --enable-demuxer=h264 --enable-muxer=mp4 \
    --enable-protocol=udp,file --enable-bsf=extract_extradata,h264_mp4toannexb --extra-ldflags=-static-libgcc
make -j"$(nproc)"
make install
cp "$WORK"/install/bin/*.dll "$OUT"/
cp "$(dirname "$(command -v gcc)")/libwinpthread-1.dll" "$OUT"/  # avutil uses it
echo "$VERSION" > "$OUT/VERSION"
echo "minimal FFmpeg $VERSION in $OUT"

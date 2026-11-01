#!/bin/sh
# Build the minimal FFmpeg the releases use, with only what Tello Revived needs: H.264 decoding,
# UDP input, saving mp4 and scaling frames (a few MB instead of 40-65 MB).
#
#     tools/build_ffmpeg.sh 9.0.2 build/ffmpeg-slim
#     uv run python tools/build.py --slim-ffmpeg build/ffmpeg-slim
#
# The version must be the one PyAV was built with (python -c "import av; print(av.ffmpeg_version_info)").
# Needs a C compiler, make and (on x86) nasm. On Windows, run it in an MSYS2 UCRT64 shell, or Git
# Bash with a MinGW gcc on PATH.
set -eu
VERSION=$1
mkdir -p "$2"
OUT=$(cd "$2" && pwd)
WORK=$(pwd)/build/ffmpeg-$VERSION
mkdir -p "$WORK/tmp"
export TMPDIR="$WORK/tmp"  # configure needs a Unix-style temp folder (matters on Windows)

case "$(uname -s)" in
    MINGW* | MSYS*) OS=windows ;;
    Darwin) OS=macos ;;
    *) OS=linux ;;
esac
case $OS in
    windows) PLATFORM="--target-os=mingw32 --arch=x86_64 --enable-w32threads --extra-ldflags=-static-libgcc" ;;
    # room in the headers to rename the libraries afterwards (see below)
    macos) PLATFORM="--enable-pthreads --install-name-dir=@loader_path --extra-ldflags=-Wl,-headerpad_max_install_names" ;;
    linux) PLATFORM="--enable-pthreads" ;;
esac
JOBS=$(nproc 2>/dev/null || sysctl -n hw.ncpu)
# macOS binds each imported function to the library it came from when PyAV was built, and PyAV's
# own libraries offer the functions of the FFmpeg libraries they link to (PyAV expects av_malloc in
# libavdevice and av_packet_alloc in libavfilter, for example). So on macOS each library is linked
# to the same FFmpeg libraries as PyAV's, as re-exports.
if [ $OS = macos ]; then
    set -- "LD_LIB=-Wl,-reexport-l%" \
        "avdevice_FFLIBS=avfilter swscale avformat avcodec swresample avutil" \
        "avfilter_FFLIBS=swscale avformat avcodec swresample avutil" \
        "avformat_FFLIBS=avcodec swresample avutil" \
        "avcodec_FFLIBS=swresample avutil"
else
    set --
fi

cd "$WORK"
[ -f "ffmpeg-$VERSION.tar.xz" ] || curl -sSfL -o "ffmpeg-$VERSION.tar.xz" "https://ffmpeg.org/releases/ffmpeg-$VERSION.tar.xz"
rm -rf "ffmpeg-$VERSION" install
tar -xf "ffmpeg-$VERSION.tar.xz"
cd "ffmpeg-$VERSION"
# shellcheck disable=SC2086  # PLATFORM is several options
./configure --prefix="$WORK/install" $PLATFORM \
    --enable-shared --disable-static --disable-programs --disable-doc --disable-debug \
    --disable-autodetect --disable-everything \
    --enable-decoder=h264 --enable-parser=h264 --enable-demuxer=h264 --enable-muxer=mp4 \
    --enable-protocol=udp,file --enable-bsf=extract_extradata,h264_mp4toannexb
make -j"$JOBS" "$@"
make install "$@"
cd "$WORK/install"

case $OS in
    windows)
        cp bin/*.dll "$OUT"/
        cp "$(dirname "$(command -v gcc)")/libwinpthread-1.dll" "$OUT"/  # avutil uses it
        ;;
    linux)
        # one file per library, named by its SONAME (libavcodec.so.63), which is what loads it
        for lib in lib/lib*.so.*; do
            soname=$(basename "$lib" | sed -E 's/^(lib[a-z]+\.so\.[0-9]+).*/\1/')
            [ -f "$OUT/$soname" ] || cp -L "$lib" "$OUT/$soname"
        done
        ;;
    macos)
        # PyAV loads libavcodec.63.1.102.dylib, but FFmpeg's libraries call each other
        # libavcodec.63.dylib: give every library and reference the full version name, then re-sign
        for lib in lib/lib*.*.*.*.dylib; do cp "$lib" "$OUT"/; done
        for lib in "$OUT"/*.dylib; do
            name=$(basename "$lib")
            install_name_tool -id "@loader_path/$name" "$lib"
            for full in "$OUT"/*.dylib; do
                full=$(basename "$full")
                short=$(echo "$full" | sed -E 's/^(lib[a-z]+\.[0-9]+)\..*/\1.dylib/')
                install_name_tool -change "@loader_path/$short" "@loader_path/$full" "$lib"
            done
            codesign --force --sign - "$lib"
        done
        ;;
esac
echo "$VERSION" > "$OUT/VERSION"
echo "minimal FFmpeg $VERSION in $OUT:"
ls -l "$OUT"

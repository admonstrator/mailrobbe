# Generator media

Recordings and photos the test data generator attaches to mails (`generator.documents`,
`RECORDING_FORMS`; `generator.fileformats.jpeg`). They are synthetic: tones, a warbling
"voice" of two harmonics with a syllable rhythm, ffmpeg's test patterns (`testsrc2`, `testsrc`,
`mandelbrot`) and a pattern of sines. No recording, picture or voice of anybody is in them.

Browsers play all of them except `wma-1.wma` (Windows Media Audio in ASF) and `avi-1.avi`
(MPEG-4 Part 2 and MP3 in AVI), which stand for the attachments that are download only.
H.264 and AAC (MP4, M4A, MOV) need a browser with these codecs: Chrome, Edge, Safari and
Firefox have them, the open-source Chromium of Playwright does not.

They were made once with ffmpeg 6.1.1 (Ubuntu 24.04) by the commands below, run in this
directory, and are committed as they came out: the generator reads these bytes, it never runs
ffmpeg. With the same ffmpeg the commands give the same bytes again; another ffmpeg or encoder
build may give others, and a changed file changes the generated archives (and the SHA-256 in
their manifests), so replace them only on purpose.

```sh
B="-hide_banner -loglevel error -y"
S="-map_metadata -1 -fflags +bitexact -flags +bitexact"
voice() {  # a warbling tone with two harmonics and a syllable rhythm: $1 Hz, $2 syllables/s
  echo "0.3*(sin(2*PI*$1*t+3*sin(2*PI*4*t))+0.5*sin(4*PI*$1*t+6*sin(2*PI*4*t)))*(0.55+0.45*sin(2*PI*$2*t))"
}
V1=$(voice 150 3.5)
V2=$(voice 220 4.2)
V3=$(voice 180 2.8)

ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V1':s=22050:d=2.5" $S -ac 1 -c:a libmp3lame -b:a 24k mp3-1.mp3
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V2':s=22050:d=3.5" $S -ac 1 -c:a libmp3lame -b:a 24k \
  -id3v2_version 0 -write_xing 0 mp3-2.mp3
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V3':s=22050:d=1.5" $S -ac 1 -c:a libmp3lame -b:a 24k mp3-3.mp3
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V2':s=22050:d=2" $S -ac 1 -c:a aac -b:a 24k -movflags +faststart m4a-1.m4a
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V3':s=22050:d=3" $S -ac 1 -c:a aac -b:a 24k -movflags +faststart m4a-2.m4a
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V1':s=22050:d=1.5" $S -ac 1 -c:a aac -b:a 24k -movflags +faststart m4a-3.m4a
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V1':s=8000:d=1.2" $S -ac 1 -c:a pcm_s16le wav-1.wav
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V2':s=8000:d=1" $S -ac 1 -c:a pcm_s16le wav-2.wav
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V3':s=48000:d=3" $S -ac 1 -c:a libopus -b:a 16k ogg-1.ogg
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V1':s=48000:d=2" $S -ac 1 -c:a libopus -b:a 16k ogg-2.ogg
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V2':s=22050:d=2" $S -ac 1 -c:a libvorbis -q:a 0 ogg-3.ogg
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V2':s=8000:d=1.5" $S -ac 1 -c:a flac -sample_fmt s16 flac-1.flac
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V3':s=8000:d=2" $S -ac 1 -c:a flac -sample_fmt s16 flac-2.flac
ffmpeg $B -f lavfi -i "aevalsrc=exprs='$V1':s=22050:d=2" $S -ac 1 -c:a wmav2 -b:a 32k wma-1.wma

H264="-c:v libx264 -pix_fmt yuv420p -preset veryslow -crf 40 -c:a aac -b:a 24k -ac 1 -shortest"
ffmpeg $B -f lavfi -i "testsrc2=size=256x144:rate=12:duration=2" \
  -f lavfi -i "sine=frequency=330:sample_rate=22050:duration=2" \
  $S $H264 -profile:v baseline -g 24 -movflags +faststart mp4-1.mp4
ffmpeg $B -f lavfi -i "testsrc2=size=240x180:rate=12:duration=3" \
  -f lavfi -i "sine=frequency=262:sample_rate=22050:duration=3" \
  $S $H264 -profile:v baseline -g 36 -movflags +faststart mp4-2.mp4
# QuickTime as a phone sends it: portrait, the index (moov) after the data
ffmpeg $B -f lavfi -i "testsrc2=size=144x256:rate=15:duration=2" \
  -f lavfi -i "sine=frequency=392:sample_rate=22050:duration=2" \
  $S $H264 -profile:v main -g 30 -f mov mov-1.mov
ffmpeg $B -f lavfi -i "testsrc=size=144x256:rate=15:duration=1.5" \
  -f lavfi -i "sine=frequency=440:sample_rate=22050:duration=1.5" \
  $S $H264 -profile:v main -g 30 -f mov mov-2.mov
ffmpeg $B -f lavfi -i "testsrc2=size=256x144:rate=12:duration=2" \
  -f lavfi -i "sine=frequency=294:sample_rate=22050:duration=2" \
  $S -c:v libvpx -b:v 60k -crf 58 -qmax 63 -deadline good -cpu-used 0 -g 24 \
  -c:a libvorbis -q:a 0 -ac 1 -shortest webm-1.webm
ffmpeg $B -f lavfi -i "testsrc2=size=256x144:rate=12:duration=3" \
  -f lavfi -i "sine=frequency=349:sample_rate=48000:duration=3" \
  $S -c:v libvpx-vp9 -b:v 0 -crf 52 -deadline good -cpu-used 0 -g 36 \
  -c:a libopus -b:a 12k -ac 1 -shortest webm-2.webm
ffmpeg $B -f lavfi -i "testsrc2=size=160x120:rate=10:duration=1" \
  -f lavfi -i "sine=frequency=220:sample_rate=22050:duration=1" \
  $S -c:v mpeg4 -vtag XVID -q:v 31 -c:a libmp3lame -b:a 24k -ac 1 -shortest avi-1.avi

ffmpeg $B -f lavfi -i "testsrc2=size=320x240" $S -frames:v 1 -q:v 8 -f mjpeg jpeg-1.jpeg
ffmpeg $B -f lavfi -i "mandelbrot=size=320x240" $S -frames:v 1 -q:v 8 -f mjpeg jpeg-2.jpeg
ffmpeg $B -f lavfi -i "nullsrc=size=320x240,geq=r='128+100*sin(X/23)':g='128+100*sin(Y/17)':b='128+100*sin((X+Y)/29)'" \
  $S -frames:v 1 -q:v 8 -f mjpeg jpeg-3.jpeg
```

| File | Content |
| --- | --- |
| `mp3-1.mp3`, `mp3-3.mp3` | MP3 (MPEG-2 Layer III, 22.05 kHz mono) behind an empty ID3v2.4 tag |
| `mp3-2.mp3` | MP3 that starts with its first frame: no ID3 tag, no Xing header |
| `m4a-1.m4a` to `m4a-3.m4a` | AAC-LC in MP4, brand `M4A `, index first |
| `wav-1.wav`, `wav-2.wav` | PCM 16 bit, 8 kHz mono, as telephone systems record |
| `ogg-1.ogg`, `ogg-2.ogg` | Opus in Ogg, as messengers send voice messages |
| `ogg-3.ogg` | Vorbis in Ogg |
| `flac-1.flac`, `flac-2.flac` | FLAC, 8 kHz mono |
| `wma-1.wma` | Windows Media Audio 2 in ASF: browsers do not play it |
| `mp4-1.mp4`, `mp4-2.mp4` | H.264 (baseline) and AAC, brand `isom`, index first (`+faststart`) |
| `mov-1.mov`, `mov-2.mov` | H.264 (main) and AAC in QuickTime, brand `qt  `, portrait, index last |
| `webm-1.webm` | VP8 and Vorbis in WebM |
| `webm-2.webm` | VP9 and Opus in WebM |
| `avi-1.avi` | MPEG-4 Part 2 (XVID) and MP3 in AVI: browsers do not play it |
| `jpeg-1.jpeg` to `jpeg-3.jpeg` | baseline JPEG (JFIF, 320x240): the photos `fileformats.jpeg` pads |

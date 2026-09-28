import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(95);
Config.setCodec('h264');
Config.setPixelFormat('yuv420p');
Config.setOverwriteOutput(true);
// Generated clips are large; decode them outside the browser.
Config.setOffthreadVideoCacheSizeInBytes(2 * 1024 * 1024 * 1024);

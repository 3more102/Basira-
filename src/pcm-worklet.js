class BasiraPcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.blocks = [];
    this.samples = 0;
    this.targetSamples = 2048;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    const copy = new Float32Array(channel);
    this.blocks.push(copy);
    this.samples += copy.length;
    if (this.samples >= this.targetSamples) {
      const joined = new Float32Array(this.samples);
      let offset = 0;
      for (const block of this.blocks) {
        joined.set(block, offset);
        offset += block.length;
      }
      this.port.postMessage({ samples: joined.buffer, sampleRate }, [joined.buffer]);
      this.blocks = [];
      this.samples = 0;
    }
    return true;
  }
}

registerProcessor("basira-pcm-capture", BasiraPcmCapture);

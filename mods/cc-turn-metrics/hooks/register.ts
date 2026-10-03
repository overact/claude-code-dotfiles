import type { EngineInterface, Register } from 'claude-code'

// Times every main-loop model request as its chunks pass through, and writes it to
// ~/.claude/statusline-metrics/<session id>.json for statusline.py: a mod cannot draw in the
// native status line slot, so this one only measures.
//
//   ttft_ms  request sent -> first chunk back (the message_start envelope)
//   tps      output_tokens / (stop chunk - first chunk): decode speed, TTFT excluded
//
// The file holds the latest request at its top level and the last HISTORY ones under `history`.
const HISTORY = 20

type Sample = {
  at: number
  model: string
  output_tokens: number
  ttft_ms: number
  first_content_ms: number | null
  gen_ms: number
  tps: number | null
}

export const register: Register = on => {
  on('turn.step', async function* ($, e, next) {
    if (e.agentId) return yield* next(e)

    const sentAt = performance.now()
    let firstAny: number | undefined
    let firstContent: number | undefined
    let stopAt: number | undefined

    const stream = next(e)
    for (;;) {
      const { value, done } = await stream.next()
      if (done) {
        if (value?.usage && firstAny !== undefined) {
          const genMs = (stopAt ?? performance.now()) - firstAny
          const tokens = value.usage.output_tokens
          await record($, {
            at: Date.now(),
            model: e.model,
            output_tokens: tokens,
            ttft_ms: Math.round(firstAny - sentAt),
            first_content_ms: firstContent === undefined ? null : Math.round(firstContent - sentAt),
            gen_ms: Math.round(genMs),
            // Below a few tokens or ~100 ms the ratio is mostly timer noise.
            tps: tokens >= 5 && genMs >= 100 ? Math.round((tokens / genMs) * 1000 * 10) / 10 : null,
          })
        }
        return value
      }
      const now = performance.now()
      firstAny ??= now
      if (value.kind !== 'engine' && value.kind !== 'stop') firstContent ??= now
      if (value.kind === 'stop') stopAt = now
      yield value
    }
  })
}

async function record($: EngineInterface, sample: Sample) {
  try {
    const home = await $.env.get('HOME')
    if (!home) return
    const path = `${home}/.claude/statusline-metrics/${await $.session.id()}.json`
    let history: Sample[] = []
    try {
      const prev = JSON.parse(await $.fs.read(path))
      if (Array.isArray(prev.history)) history = prev.history
    } catch {
      // first request of the session, or a file from before `history`
    }
    history = [...history, sample].slice(-HISTORY)
    await $.fs.write(path, JSON.stringify({ ...sample, history }))
  } catch {
    // Measurement is best effort; never disturb the turn.
  }
}

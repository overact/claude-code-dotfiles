import { expect, test } from 'claude-code/testing'

const spin = (ms: number) => {
  const end = performance.now() + ms
  while (performance.now() < end) {}
}

/** Stubs what the mod asks Claude Code; the engine's step answers after `wait` ms, then streams for `gen` ms. */
async function boot($: any, on: any, outputTokens: number, wait = 30, gen = 150) {
  const written: { path: string; text: string }[] = []
  on('env.get', (_: unknown, e: { name: string }) => ({ value: e.name === 'HOME' ? '/home/user' : undefined }))
  on('session.id', () => ({ value: 'sess-1' }))
  const files = new Map<string, string>()
  on('fs.write', (_: unknown, e: { path: string; text: string }) => {
    written.push(e)
    files.set(e.path, e.text)
    return { value: undefined }
  })
  on('fs.read', (_: unknown, e: { path: string }) => {
    const text = files.get(e.path)
    if (text === undefined) throw new Error('ENOENT')
    return { value: text }
  })
  on('turn.step', async function* (_: unknown, e: { turnId: string; index: number }) {
    spin(wait)
    yield { kind: 'text', index: 0, text: 'hi' }
    spin(gen)
    const usage = { model: 'claude-opus-5-5', input_tokens: 1, output_tokens: outputTokens, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }
    yield { kind: 'stop', stopReason: 'end_turn', usage }
    return { turnId: e.turnId, index: e.index, answer: 'hi', toolUses: [], stopReason: 'end_turn', usage }
  })
  on('session.start', () => ({ cwd: '/work' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

  const step = async (agentId?: string) => {
    const stream = $.turn.step({ turnId: 't', index: 0, model: 'claude-opus-5-5', messageCount: 3, ...(agentId && { agentId }) })
    let s = await stream.next()
    while (s.done !== true) s = await stream.next()
  }
  return { written, step }
}

test('a main-loop request is timed into the session file', async ($, on) => {
  const { written, step } = await boot($, on, 300)
  await step()
  expect(written.length).toBe(1)
  expect(written[0]!.path).toBe('/home/user/.claude/statusline-metrics/sess-1.json')
  const m = JSON.parse(written[0]!.text)
  expect(m.output_tokens).toBe(300)
  expect(m.ttft_ms).toBeGreaterThanOrEqual(25)
  expect(m.gen_ms).toBeGreaterThanOrEqual(140)
  // 300 tokens over ~150 ms of decoding: around 2000 tok/s, TTFT not counted
  expect(m.tps).toBeGreaterThan(1000)
  expect(m.tps).toBeLessThan(2200)
})

test('a subagent request is not recorded', async ($, on) => {
  const { written, step } = await boot($, on, 300)
  await step('agent-1')
  expect(written.length).toBe(0)
})

test('a response of a few tokens keeps its TTFT but has no speed', async ($, on) => {
  const { written, step } = await boot($, on, 3)
  await step()
  const m = JSON.parse(written[0]!.text)
  expect(m.ttft_ms).toBeGreaterThanOrEqual(25)
  expect(m.tps).toBe(null)
})

test('the file keeps the last requests under history, newest at the top level', async ($, on) => {
  const { written, step } = await boot($, on, 300, 10, 120)
  await step()
  await step()
  const m = JSON.parse(written.at(-1)!.text)
  expect(m.history.length).toBe(2)
  expect(m.history[1].at).toBe(m.at)
  expect(m.history[0].output_tokens).toBe(300)
})

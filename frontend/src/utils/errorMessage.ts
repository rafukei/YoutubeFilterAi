export function getErrorMessage(err: any, fallback = 'Operation failed'): string {
  const detail = err?.response?.data?.detail

  if (typeof detail === 'string' && detail.trim()) return detail

  if (Array.isArray(detail)) {
    const first = detail[0]
    if (typeof first === 'string' && first.trim()) return first
    if (first && typeof first === 'object') {
      const msg = first.msg || first.message || first.type
      if (typeof msg === 'string' && msg.trim()) return msg
      try {
        return JSON.stringify(first)
      } catch {
        // ignore
      }
    }
  }

  if (detail && typeof detail === 'object') {
    const msg = detail.msg || detail.message || detail.type
    if (typeof msg === 'string' && msg.trim()) return msg
    try {
      return JSON.stringify(detail)
    } catch {
      // ignore
    }
  }

  if (typeof err?.message === 'string' && err.message.trim()) return err.message

  return fallback
}

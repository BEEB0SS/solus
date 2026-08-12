// Maps a raw user input (repo path, project folder, Onshape URL) to the
// connector config + display name for each source type.
export function sourceInputToConfig(sourceType: string, input: string): { config: Record<string, any>; name: string } {
  const trimmed = input.trim()
  if (sourceType === 'github') {
    return { config: { path: trimmed }, name: trimmed.split('/').pop() || 'github-repo' }
  }
  if (sourceType === 'kicad') {
    return { config: { path: trimmed }, name: trimmed.split('/').pop() || 'kicad-project' }
  }
  if (sourceType === 'onshape') {
    return { config: { url: trimmed }, name: 'onshape-model' }
  }
  return { config: {}, name: '' }
}

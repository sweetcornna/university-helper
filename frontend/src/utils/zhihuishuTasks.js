export const TERMINAL_ZHIHUISHU_TASK_STATUSES = new Set([
  'completed',
  'failed',
  'cancelled',
  'error',
])

const ACTION_TRANSITIONS = {
  pause: { from: new Set(['running', 'starting', 'queued']), to: 'paused' },
  resume: { from: new Set(['paused']), to: 'running' },
  cancel: { from: null, to: 'cancelled' },
}

export const applyTaskActionToRecords = (
  taskRecords,
  { action, taskId = '', message = '', updatedAt = '' },
) => {
  const transition = ACTION_TRANSITIONS[action]
  if (!transition) return taskRecords

  return taskRecords.map((task) => {
    if (taskId && task.taskId !== taskId) return task
    const status = String(task.status || 'unknown')
    if (TERMINAL_ZHIHUISHU_TASK_STATUSES.has(status)) return task
    if (transition.from && !transition.from.has(status)) return task
    return {
      ...task,
      status: transition.to,
      message: message || task.message,
      updatedAt: updatedAt || task.updatedAt,
    }
  })
}

export const applyCourseProgressToTaskRecords = (
  taskRecords,
  { courseId, activeTaskId, progress, updatedAt }
) => {
  if (!courseId || !activeTaskId) {
    return taskRecords
  }

  const statusValue = String(progress?.status || 'running')
  const messageValue = progress?.message || '进度已更新'
  const currentVideo = progress?.current_video || progress?.currentTask || ''
  const total = Number(progress?.total ?? 0) || 0
  const completed = Number(progress?.completed ?? 0) || 0
  const failed = Number(progress?.failed ?? 0) || 0
  const percentage = Number(progress?.percentage ?? 0) || 0

  return taskRecords.map((task) => {
    if (task.taskId !== activeTaskId || task.courseId !== courseId) {
      return task
    }

    return {
      ...task,
      status: statusValue,
      message: messageValue,
      currentTask: currentVideo,
      total,
      completed,
      failed,
      percentage,
      updatedAt,
      progress: {
        ...(task.progress || {}),
        ...(progress || {}),
        status: statusValue,
        message: messageValue,
        current_video: currentVideo,
        total,
        completed,
        failed,
        percentage,
      },
    }
  })
}

// Groups a flat video list from /course/zhihuishu/videos into its chapters, in
// course order, each with its videos. Videos without a chapter id cannot be
// used as an end point, so they are left out.
export const groupVideosByChapter = (videos) => {
  const chapters = []
  const byId = new Map()
  ;(Array.isArray(videos) ? videos : []).forEach((video) => {
    const id = String(video?.chapter_id ?? video?.chapterId ?? '').trim()
    if (!id) return
    let chapter = byId.get(id)
    if (!chapter) {
      chapter = { id, title: String(video?.chapter_title ?? video?.chapterTitle ?? '').trim(), videos: [] }
      byId.set(id, chapter)
      chapters.push(chapter)
    }
    chapter.videos.push(video)
  })
  return chapters.map((chapter, index) => ({
    ...chapter,
    title: chapter.title || `第 ${index + 1} 章`,
    videoCount: chapter.videos.length,
  }))
}

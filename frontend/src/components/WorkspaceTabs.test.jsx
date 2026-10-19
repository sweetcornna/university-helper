import { useState } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, test } from 'vitest'
import WorkspaceTabs from './WorkspaceTabs'
import useWorkspaceTab from './useWorkspaceTab'

const TABS = [{ id: 'courses', label: '课程' }, { id: 'settings', label: '配置' }, { id: 'tasks', label: '任务' }]

function Workspace() {
  const [activeTab, setActiveTab] = useWorkspaceTab(TABS, 'courses', { config: 'settings' })
  const [draft, setDraft] = useState('')
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <WorkspaceTabs id="test" label="学习工作区" tabs={TABS} activeTab={activeTab} onChange={setActiveTab} />
      <div id={`test-panel-${activeTab}`} role="tabpanel" aria-labelledby={`test-tab-${activeTab}`}>
        {activeTab === 'courses' && <input aria-label="课程备注" value={draft} onChange={(event) => setDraft(event.target.value)} />}
        {activeTab === 'settings' && <p>学习配置内容</p>}
        {activeTab === 'tasks' && <p>任务执行内容</p>}
      </div>
      <output data-testid="location">{location.pathname}{location.search}{location.hash}</output>
      <button type="button" onClick={() => navigate(-1)}>后退</button>
      <button type="button" onClick={() => navigate(1)}>前进</button>
    </>
  )
}

const renderWorkspace = (entry) => render(
  <MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Workspace /></MemoryRouter>
)

afterEach(cleanup)

describe('linked workspace navigation', () => {
  test.each([
    ['/chaoxing-fanya', '课程'],
    ['/chaoxing-fanya?tab=tasks', '任务'],
    ['/chaoxing-fanya?tab=unknown', '课程'],
    ['/chaoxing-fanya?tab=config', '配置'],
  ])('opens %s in the expected section', (entry, label) => {
    renderWorkspace(entry)
    expect(screen.getByRole('tab', { name: label })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', screen.getByRole('tab', { name: label }).id)
  })

  test('keeps query parameters and drafts across back/forward and exposes real links', async () => {
    const user = userEvent.setup()
    renderWorkspace('/chaoxing-fanya?course=42#progress')
    await user.type(screen.getByRole('textbox', { name: '课程备注' }), '保留的选择')
    expect(screen.getByRole('tab', { name: '任务' })).toHaveAttribute('href', '/chaoxing-fanya?course=42&tab=tasks#progress')
    await user.click(screen.getByRole('tab', { name: '任务' }))
    expect(screen.getByText('任务执行内容')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '后退' }))
    expect(screen.getByRole('textbox')).toHaveValue('保留的选择')
    await user.click(screen.getByRole('button', { name: '前进' }))
    expect(screen.getByRole('tab', { name: '任务' })).toHaveAttribute('aria-selected', 'true')
  })

  test('supports arrow, Home and End keys with focus on the chosen tab', async () => {
    const user = userEvent.setup()
    renderWorkspace('/zhihuishu-panel')
    screen.getByRole('tab', { name: '课程' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: '配置' })).toHaveFocus()
    expect(screen.getByText('学习配置内容')).toBeInTheDocument()
    await user.keyboard('{End}')
    expect(screen.getByRole('tab', { name: '任务' })).toHaveFocus()
    await user.keyboard('{Home}')
    expect(screen.getByRole('tab', { name: '课程' })).toHaveFocus()
  })
})

import { describe, expect, test } from 'vitest'
import { normalizeChatActivities, parseChatActivityLink, resolveChatSigninTarget } from './chatSignin'

describe('group sign-in links and activity types', () => {
  test.each([
    ['https://mobilelearn.chaoxing.com/pptSign/stuSign?aid=123&chatId=456', { activeId: '123', chatId: '456' }],
    ['https://mobilelearn.chaoxing.com/widget/sign?activeId=123', { activeId: '123', chatId: '' }],
    ['https://mobilelearn.chaoxing.com/widget/sign?activePrimaryId=123&chatid=456', { activeId: '123', chatId: '456' }],
  ])('parses official activity identifiers in %s', (link, expected) => {
    expect(parseChatActivityLink(link)).toEqual(expected)
  })

  test.each([
    'javascript:alert(1)',
    'https://chaoxing.com.example.com/sign?aid=123',
    'https://chaoxing.com@evil.example/sign?aid=123',
    'https://attacker@mobilelearn.chaoxing.com/sign?aid=123',
    'https://example.com/sign?aid=123',
    'https://mobilelearn.chaoxing.com/sign',
    'https://mobilelearn.chaoxing.com/sign?aid=123&activeId=456',
  ])('rejects an invalid or ambiguous activity URL %s', (link) => {
    expect(() => parseChatActivityLink(link)).toThrow()
  })

  test('resolves direct ids or a link without sending the URL to the server', () => {
    expect(resolveChatSigninTarget({ chatId: ' 456 ', activeId: ' 123 ' })).toEqual({ chatId: '456', activeId: '123' })
    expect(resolveChatSigninTarget({ activityLink: 'https://mobilelearn.chaoxing.com/sign?aid=123&chatId=456' })).toEqual({ chatId: '456', activeId: '123' })
    expect(() => resolveChatSigninTarget({ chatId: '789', activityLink: 'https://mobilelearn.chaoxing.com/sign?aid=123&chatId=456' })).toThrow('不一致')
    expect(() => resolveChatSigninTarget({ chatId: 'abc', activeId: '123' })).toThrow('正整数')
  })

  test('preserves photo and unknown types instead of treating them as ordinary sign-in', () => {
    expect(normalizeChatActivities({ data: { tasks: [
      { chatId: '1', activeId: '10', type: 'photo' },
      { chat_id: '1', active_id: '11' },
    ] } }).map((task) => task.type)).toEqual(['photo', 'unknown'])
    expect(normalizeChatActivities({ data: [] })).toEqual([])
  })
})

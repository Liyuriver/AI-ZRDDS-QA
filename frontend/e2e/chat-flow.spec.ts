import { expect, test } from '@playwright/test'

test('registers, chats, restores evidence, renames and deletes a conversation', async ({
  page,
}) => {
  await page.goto('/register')
  await page.getByPlaceholder('请输入用户名').fill('e2e-user')
  await page.getByPlaceholder('请输入邮箱').fill('e2e@example.com')
  await page.getByPlaceholder('请输入至少 8 位密码').fill('e2e-pass')
  await page.getByPlaceholder('请再次输入密码').fill('e2e-pass')
  await page.getByRole('button', { name: '创建账号' }).click()

  await expect(page).toHaveURL(/\/chat/)
  await expect(page.getByRole('heading', { name: '历史会话' })).toBeVisible()

  await page.getByLabel('问题输入框').fill('如何排查 ZRDDS 构建错误？')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('正在检索知识库')).toBeVisible()
  await expect(page.getByText('参考来源')).toBeVisible()
  await expect(page.getByText('ZRDDS故障排查指南.pdf')).toBeVisible()

  await page.reload()
  await expect(page.getByRole('heading', { name: '如何排查 ZRDDS 构建错误？' })).toBeVisible()
  await expect(page.getByText('参考来源')).toBeVisible()

  await page.getByRole('button', { name: '重命名会话' }).click()
  const renameDialog = page.getByRole('dialog', { name: '重命名会话' })
  await renameDialog.getByRole('textbox').fill('构建错误排查')
  await renameDialog.getByRole('button', { name: '保存' }).click()
  await expect(page.getByRole('heading', { name: '构建错误排查' })).toBeVisible()

  await page.getByRole('button', { name: '删除会话' }).click()
  const deleteDialog = page.getByRole('dialog', { name: '删除会话' })
  await deleteDialog.getByRole('button', { name: '删除' }).click()
  await expect(page.getByText('暂无历史会话')).toBeVisible()
})

test('logs in with the demo account', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill('123')
  await page.getByPlaceholder('请输入密码').fill('87654321')
  await page.getByRole('button', { name: '登录', exact: true }).click()

  await expect(page).toHaveURL(/\/chat/)
  await expect(page.getByText('当前会话')).toBeVisible()
})

test('starts a conversation from a desktop suggestion card', async ({ page }) => {
  await page.goto('/login')
  await page.getByPlaceholder('请输入用户名').fill('123')
  await page.getByPlaceholder('请输入密码').fill('87654321')
  await page.getByRole('button', { name: '登录', exact: true }).click()

  await page.getByRole('button', { name: /开发问题/ }).click()

  await expect(
    page.getByRole('heading', { name: 'ZRDDS 开发环境需要哪些依赖和配置？' }),
  ).toBeVisible()
  await expect(page.getByText('参考来源')).toBeVisible()
})

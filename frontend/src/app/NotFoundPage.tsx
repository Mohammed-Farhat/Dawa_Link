import { Anchor, Container, Stack, Title } from '@mantine/core'
import { Link } from 'react-router-dom'

import { strings } from '../strings/en'

export function NotFoundPage() {
  return (
    <Container size="xs" py="xl">
      <Stack gap="md">
        <Title order={1} size={26}>
          {strings.notFound.title}
        </Title>
        <Anchor component={Link} to="/">
          {strings.notFound.back}
        </Anchor>
      </Stack>
    </Container>
  )
}

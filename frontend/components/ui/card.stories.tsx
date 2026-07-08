import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "./card";
import { Button } from "./button";

const meta: Meta<typeof Card> = {
  title: "UI/Card",
  component: Card,
};
export default meta;

type Story = StoryObj<typeof Card>;

export const Default: Story = {
  render: () => (
    <Card style={{ maxWidth: 360 }}>
      <CardHeader>
        <CardTitle>Plan review</CardTitle>
        <CardDescription>Approve or request changes before execution.</CardDescription>
      </CardHeader>
      <CardContent>
        <p>3 steps queued, 1 pending approval gate.</p>
      </CardContent>
      <CardFooter>
        <Button size="sm">Approve</Button>
      </CardFooter>
    </Card>
  ),
};

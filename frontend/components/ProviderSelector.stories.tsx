import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import * as React from "react";

import { ProviderSelector, type ProviderId } from "./ProviderSelector";

const meta: Meta<typeof ProviderSelector> = {
  title: "Config/ProviderSelector",
  component: ProviderSelector,
};
export default meta;

type Story = StoryObj<typeof ProviderSelector>;

function InteractiveSelector({ initial }: { initial: ProviderId }) {
  const [value, setValue] = React.useState<ProviderId>(initial);
  return <ProviderSelector value={value} onChange={setValue} />;
}

export const StubSelected: Story = {
  render: () => <InteractiveSelector initial="stub" />,
};

export const OllamaSelected: Story = {
  render: () => <InteractiveSelector initial="ollama" />,
};

export const OpenAiSelected: Story = {
  render: () => <InteractiveSelector initial="openai" />,
};

export const Disabled: Story = {
  args: { value: "stub", disabled: true, onChange: () => {} },
};

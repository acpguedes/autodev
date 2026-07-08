"use client";

import * as React from "react";

type PanelErrorBoundaryProps = {
  panelId: string;
  children: React.ReactNode;
};

type PanelErrorBoundaryState = {
  hasError: boolean;
};

/**
 * Isolates plugin panels: a panel that throws during render is replaced by
 * an inline alert and never takes down the rest of the app (E10-S4 CNF).
 */
export class PanelErrorBoundary extends React.Component<
  PanelErrorBoundaryProps,
  PanelErrorBoundaryState
> {
  state: PanelErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): PanelErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.error(`[panels] panel "${this.props.panelId}" crashed`, error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="rounded-md border border-destructive bg-destructive p-3 text-sm text-destructive-foreground"
        >
          The panel &quot;{this.props.panelId}&quot; failed to render and was isolated.
          The rest of the app is unaffected.
        </div>
      );
    }
    return this.props.children;
  }
}

export default PanelErrorBoundary;

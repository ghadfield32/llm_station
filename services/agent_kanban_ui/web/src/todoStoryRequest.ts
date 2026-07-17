export type TodoStoryRequest = {
  generation: number;
  signal: AbortSignal;
};

export class TodoStoryRequestGate {
  private generation = 0;
  private controller: AbortController | null = null;

  begin(): TodoStoryRequest {
    this.controller?.abort();
    this.controller = new AbortController();
    return {
      generation: ++this.generation,
      signal: this.controller.signal,
    };
  }

  isCurrent(request: TodoStoryRequest): boolean {
    return request.generation === this.generation && !request.signal.aborted;
  }

  close(): void {
    this.controller?.abort();
    this.controller = null;
    this.generation += 1;
  }
}

export type TodoStoryMutation = {
  generation: number;
  todoId: string;
  signal: AbortSignal;
};

export class TodoStoryMutationGate {
  private generation = 0;
  private controller: AbortController | null = null;

  begin(todoId: string): TodoStoryMutation {
    this.controller?.abort();
    this.controller = new AbortController();
    return {
      generation: ++this.generation,
      todoId,
      signal: this.controller.signal,
    };
  }

  invalidate(): void {
    this.controller?.abort();
    this.controller = null;
    this.generation += 1;
  }

  isCurrent(mutation: TodoStoryMutation, todoId: string | null): boolean {
    return (
      mutation.generation === this.generation
      && mutation.todoId === todoId
      && !mutation.signal.aborted
    );
  }
}

export function isDescriptionConflictStatus(status: number): boolean {
  return status === 409;
}

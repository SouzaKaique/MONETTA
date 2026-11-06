import { AfterViewInit, Component, ElementRef, input, output, viewChild } from '@angular/core';

/** Janela modal nativa: já resolve foco, Esc e fundo. No celular vira painel inferior. */
@Component({
  selector: 'app-dialog',
  template: `
    <dialog #dialog (close)="closed.emit()" (cancel)="closed.emit()">
      <header>
        <h2>{{ heading() }}</h2>
        <button type="button" class="close" aria-label="Fechar" (click)="close()">
          <i class="bi bi-x-lg" aria-hidden="true"></i>
        </button>
      </header>
      <ng-content />
    </dialog>
  `,
  styles: `
    dialog {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      color: var(--ink);
      max-height: 90dvh;
      max-width: 480px;
      overflow-y: auto;
      padding: 1.25rem;
      width: calc(100% - 2rem);
    }
    dialog::backdrop { background: rgb(0 0 0 / 40%); }
    header { align-items: center; display: flex; justify-content: space-between; margin-bottom: 1rem; }
    h2 { font-family: var(--font-display); font-size: 1.25rem; font-weight: 400; margin: 0; }
    .close { background: none; border: 0; color: var(--ink-3); padding: 0.25rem; }
    @media (max-width: 575.98px) {
      dialog {
        border-radius: var(--radius) var(--radius) 0 0;
        margin: auto 0 0;
        max-width: 100%;
        width: 100%;
      }
    }
  `,
})
export class Dialog implements AfterViewInit {
  readonly heading = input.required<string>();
  readonly closed = output<void>();
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  ngAfterViewInit(): void {
    this.dialog().nativeElement.showModal();
  }

  close(): void {
    this.dialog().nativeElement.close();
    // O evento nativo só dispara quando a página desenha; em segundo plano ele não chega.
    this.closed.emit();
  }
}

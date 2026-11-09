import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { SwUpdate } from '@angular/service-worker';
import { filter } from 'rxjs';

/** Até aqui, quem abre o app ainda não começou a preencher nada. */
const JUST_OPENED_MS = 10_000;

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  template: '<router-outlet />',
})
export class App {
  constructor() {
    const updates = inject(SwUpdate);
    if (!updates.isEnabled) return;
    // Sem isso, a versão guardada pelo navegador continua até fechar todas as abas.
    updates.versionUpdates
      .pipe(filter((e) => e.type === 'VERSION_READY'))
      .subscribe(() => {
        if (performance.now() < JUST_OPENED_MS) {
          location.reload();
          return;
        }
        // Com o app em uso, espera a aba sair de vista para não perder o que está sendo digitado.
        document.addEventListener(
          'visibilitychange',
          () => {
            if (document.hidden) location.reload();
          },
          { once: true },
        );
      });
  }
}

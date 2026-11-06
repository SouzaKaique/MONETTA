import { Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

/** Área ainda não construída: informa o que virá, sem simular funcionalidade. */
@Component({
  selector: 'app-upcoming',
  template: `
    <h1 class="page-title">{{ data['title'] }}</h1>
    <div class="card-m mt-3 fade-up">
      <p class="subtle mb-1">Chega na Etapa {{ data['stage'] }}</p>
      <p class="mb-0">{{ data['description'] }}</p>
    </div>
  `,
})
export class Upcoming {
  protected readonly data = inject(ActivatedRoute).snapshot.data;
}

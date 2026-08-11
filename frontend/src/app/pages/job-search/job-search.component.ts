import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  selector: 'app-job-search',
  standalone: true,
  imports: [],
  templateUrl: './job-search.component.html',
  styleUrl: './job-search.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class JobSearchComponent {}

from django.core.management.base import BaseCommand

from ...tasks import enqueue_task, process_new_joins


class Command(BaseCommand):
    help = "Queue automated security audits for newly joined mains"

    def handle(self, *args, **options):
        enqueue_task(process_new_joins)
        self.stdout.write(self.style.SUCCESS("Queued new-join audit processing."))

# backup_operations.py

import os
import shutil
from datetime import datetime

class BackupOperations:
    def __init__(self, source_directory, backup_directory):
        self.source_directory = source_directory
        self.backup_directory = backup_directory

    def create_backup(self):
        if not os.path.exists(self.backup_directory):
            os.makedirs(self.backup_directory)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(self.backup_directory, f'backup_{timestamp}')
        shutil.copytree(self.source_directory, backup_path)
        print(f'Backup created at: {backup_path}')

    def restore_backup(self, backup_path):
        if os.path.exists(backup_path):
            shutil.rmtree(self.source_directory)
            shutil.copytree(backup_path, self.source_directory)
            print(f'Restored from backup: {backup_path}')
        else:
            print('Backup path does not exist.')

if __name__ == '__main__':
    source = 'path/to/source'
    backup = 'path/to/backup'
    backup_ops = BackupOperations(source, backup)
    backup_ops.create_backup()
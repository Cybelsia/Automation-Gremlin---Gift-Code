# Control.py

class Control:
    def __init__(self, name):
        self.name = name

    def start(self):
        print(f'{self.name} started')

    def stop(self):
        print(f'{self.name} stopped')

# Example usage
if __name__ == '__main__':
    control = Control('Sample Control')
    control.start()
    control.stop()
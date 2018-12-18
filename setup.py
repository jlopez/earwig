from setuptools import setup

setup(name='earwig',
      version='0.1',
      description='The crawling bug that crawls bugs',
      url='http://github.com/jlopez/earwig',
      author='Jesus Lopez',
      author_email='jesus@jesusla.com',
      license='MIT',
      packages=['earwig'],
      entry_points={
          'console_scripts': [
              'earwig = earwig.cli:main'
          ]
      },
      install_requires=[
          'beautifulsoup4',
          'dateparser',
          'requests',
          'selenium',
          'ujson'
      ])

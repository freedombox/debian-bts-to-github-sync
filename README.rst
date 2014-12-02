
Debian BTS to GitHub Issues sync
================================

Mirrors bugs from the Debian BTS to GitHub Issues

Create a API token on GitHub and a label that will be used to tag
the mirrored bugs.

Create a configuration file as::

    ---
    github_api_token: it31might32look74real42but392i24made3it34up
    sync_label: debian-bts

    repositories:
    - debian_pkg: <Debian package name>
      github_repo: <username>/<project name>



Development status
------------------

In development

Roadmap
-------

* Implement more safety checks

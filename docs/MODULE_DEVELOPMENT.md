# Module Development Guide

Creator Intelligence now uses dependency-aware application modules.

## Module package

A module needs one public factory:

```python
def create_module():
    return MyModule()
```

The returned object must expose:

```python
metadata = ModuleMetadata(...)
def register(self, registry): ...
```

## Registration surfaces

Modules may register:

- services
- navigation pages
- importers
- lifecycle/event hooks

## Service registration

```python
registry.register_service(ServiceBinding(
    key="my_service",
    factory=lambda context: MyService(context.db),
    singleton=True,
    module_id=self.metadata.module_id,
))
```

Retrieve a service using:

```python
service = registry.resolve("my_service")
```

## Navigation registration

```python
registry.register_navigation(NavigationItem(
    label="My Page",
    factory=lambda: MyPage(registry.resolve("my_service")),
    order=50,
    module_id=self.metadata.module_id,
))
```

Page objects are created lazily after modules have registered.

## Importer registration

```python
registry.register_importer(ImporterBinding(
    importer_id="my_export",
    label="My Export",
    detector=lambda path: path.endswith(".csv"),
    importer_factory=lambda context: MyImporter(context.db),
    module_id=self.metadata.module_id,
))
```

## Dependencies

Declare module IDs in metadata:

```python
dependencies=("storage", "analytics")
```

Modules load in the order listed in `config/modules.json`.

## Failure isolation

A module import or registration failure is recorded in the registry. Other
independent modules continue loading. Page-construction failures show a local
failure page rather than terminating the desktop application.

## Adding future platforms

TikTok, Instagram, Kick, and other platforms should each be separate modules.
They may add:

- platform-specific importers
- analytics services
- pages
- prediction feature providers
- content-link adapters
- integration settings

The core application does not need modification when the module uses the
existing registration surfaces.

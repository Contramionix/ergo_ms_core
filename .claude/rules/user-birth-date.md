---
paths:
  - "modules/**"
---
<!-- Сгенерировано .claude/scripts/sync_claude_rules.py из .cursor/rules. Не редактировать. -->

# Дата рождения и возраст

Дата рождения пользователя платформы хранится один раз: поле `birth_date` модели `UserProfile` в приложении `cms_adp`. Человек задаёт её в настройках профиля, в блоке «Дополнительная информация», через `DatePicker`.

Возраст в модуле считают из этой даты в момент показа. Отдельную колонку возраста не хранят и не просят ввести заново.

## Обязательно

- На сервере модуля дату читают из `UserProfile` этого пользователя.
- На клиенте берут `adp_profile.birth_date` уже загруженного профиля (`YYYY-MM-DD` или пусто).
- Если даты нет, человека ведут заполнить настройки профиля.

## Запрещено

Для пользователя платформы в модуле нельзя заводить своё поле даты рождения или возраста и нельзя рисовать свой `DatePicker` или числовой ввод возраста.

```python
# BAD — вторая дата рождения у того же пользователя
class PersonCard(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    birth_date = models.DateField()
    age = models.PositiveSmallIntegerField()
```

```python
# GOOD — дата уже лежит в профиле
from src.core.cms.adp.models import UserProfile

profile = UserProfile.objects.filter(user_id=user.pk).only('birth_date').first()
birth_date = profile.birth_date if profile else None
```

```vue
<!-- BAD — свой ввод даты или возраста -->
<DatePicker v-model="person.birthDate" />
<input v-model="person.age" type="number" />
```

Человек без учётной записи платформы под это правило не попадает: поля профиля у него нет. Его дата рождения хранится в карточке человека ядра (`Person.birth_date`), а не в модуле — см. [`person.mdc`](../../.cursor/rules/person.mdc). Пока учётка привязана к карточке, источник даты — `UserProfile`.

## Связанные правила

| Тема | Файл |
|------|------|
| Модель пользователя | [`django.mdc`](../../.cursor/rules/django.mdc) |
| Модули | [`modules.mdc`](../../.cursor/rules/modules.mdc) |
| Человек без учётки | [`person.mdc`](../../.cursor/rules/person.mdc) |
| Выбор даты | [`components.mdc`](../../.cursor/rules/components.mdc) |

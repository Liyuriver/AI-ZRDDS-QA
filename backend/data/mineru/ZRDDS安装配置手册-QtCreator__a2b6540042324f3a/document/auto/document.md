## 1. 环境简述

在 Windows中，ZRDDS可在QT环境下使用。具体环境如下：

<sup></sup> mingw 版本为 4.8.2。

<sup></sup> qt 安装版本为 4.8.3（qt-win-opensource-4.8.3-mingw.exe）。

<sup></sup> Qt Creator 安装版本为 3.4.0（qt-creator-opensource-windows-x86-3.4.0.exe）。

## 2. 项目配置

要使用ZRDDS中间件需要包含头文件所在目录，库文件所在目录，库文件名，使用C++库需要添加预编译符。以上配置可在 Qt Creator 创建的项目中的.pro 文件中手动设置，具体设置方式如下：

头文件目录：在.pro 文件（图 1）中键入 INCLUDEPATH += dir1 dir2，dir1，dir2 为头文件目录，用 C++语言为\$\$quote(\$(ZRDDS\_HOME)\include\ZRDDSCoreInterface)和\$\$quote(\$(ZRDDS\_HOME)\include\CPlusPlusInterface) ； 用 C 语 言 为 \$\$quote(\$(ZRDDS\_HOME)\include\ZRDDSCoreInterface) 和 \$\$quote(\$(ZRDDS\_HOME)\include\CInterface)。其中\$(ZRDDS\_HOME)为 ZRDDS 安装目录，用\$\$quote()包住每条路径（图2、图3），以避免路径中包含空格所引起的编译错误。

![](images/faa827a3f19cd4a4f9af4838312c92ab9d41c61c857ffebee484e1b9cc245265.jpg)

图 1 项目的 pro 文件

图 2 C++头文件目录  
INCLUDEPATH += \$\$quote(\$(ZRDDS\_HOME)\include\ZRDDSCoreInterface) \$\$quote(\$(ZRDDS\_HOME)\include\CPlusPlusInterface)  
图 3 C 头文件目录

 库文件及其所在目录：在.pro 文件中键入 LIBS+=-L dir –llib。dir 为库文件所在目录，跟在-L 之后，为\$\$quote(\$(ZRDDS\_HOME)\lib)。lib 为库文件名，不带后缀，跟在-l之后，分为 ZRDDS 库（见表 1）以及 Windows 相关库（ws2\_32，wsock32，iphlpapi）。

表 1 Window 下 qt 环境库文件选择
<table><tr><td>语言</td><td>编译所需库文件</td><td>说明</td><td>预编译符</td></tr><tr><td colspan="1" rowspan="2">C++</td><td colspan="1" rowspan="1">ZRDDSCppzd.lib</td><td colspan="1" rowspan="1">Debug版本静态库</td><td colspan="1" rowspan="1">_ZRDDSCPPINTERFACE</td></tr><tr><td colspan="1" rowspan="1">ZRDDSCppz.lib</td><td colspan="1" rowspan="1">Release版本静态库</td><td colspan="1" rowspan="1">_ZRDDSCPPINTERFACE</td></tr><tr><td colspan="1" rowspan="2">C</td><td colspan="1" rowspan="1">ZRDDSCzd.lib</td><td colspan="1" rowspan="1">Debug 版本静态库</td><td colspan="1" rowspan="1"></td></tr><tr><td colspan="1" rowspan="1">ZRDDSCz.lib</td><td colspan="1" rowspan="1">Release版本静态库</td><td colspan="1" rowspan="1"></td></tr></table>

<sup></sup> 预编译符：在.pro 文件中键入 DEFINES += \_ZRDDSCPPINTERFACE。使用 ZRDDS 的 C++库时需要添加这个预编译符。

DEFINES +=ZRDDSCPPINTERFACE  
图 4 预编译符

<sup></sup> 编译设置：若出现 not permitted with -fno-rtti 问题，在.pro 文件中键入 CONFIG += rtti。

![](images/35e0bef8a1321b72d04322f27bb40caa632c08b8895b49c9fcbfd21f1160df9e.jpg)  
图 5 编译设置 rtti

至此，Windows下qt环境ZRDDS项目配置完成，以C++为例，图 6为具体配置示例。

QT += core   
QT -= gui   
TARGET = DDSApp   
CONFIG += console   
6CONFIG -= app bundle   
CONFIG G += rtti   
TEMPLATE = app   
SOURCES +=\   
Charseq.cpp\   
Charseq\_publication.cpp   
CharSeqTypeSupport.cpp   
HEADERS +=   
CharSeq.h\   
CharSegDataReader.h   
CharSeqDataWriter.h \   
CharSeqTypeSupport.h   
INCLUDEPATH += \$\$quote(\$(ZRDDS HOME)\include\ZRDDSCoreInterface) \$\$quote(\$(ZRDDS HOME)\include\CPlusPlusInterface)   
LIBS += -L \$\$quote(\$(ZRDDS HOME)\lib) -1zRDDSCppzd -1ws2 32 -1wsock32 -liphlpapi   
DEFINES += ZRDDSCPPINTERFACE   
TARGET = CharSeq\_pub  
图 6 pro 配置
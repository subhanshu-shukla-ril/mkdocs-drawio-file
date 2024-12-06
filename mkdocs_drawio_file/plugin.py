import os
import re
import string
import logging
import mkdocs
from lxml import etree
from bs4 import BeautifulSoup
from mkdocs.plugins import BasePlugin
from pkg_resources import resource_filename

class DrawioFilePlugin(BasePlugin):
    """
    Plugin for embedding DrawIO Diagrams into MkDocs documentation with local viewer
    """
    config_scheme = (
        ("file_extension", mkdocs.config.config_options.Type(str, default=".drawio")),
    )

    def __init__(self):
        self.log = logging.getLogger("mkdocs.plugins.diagrams")
        self.parsed_diagrams_cache = {}
        self.viewer_script_path = self._get_local_viewer_script()

    def _get_local_viewer_script(self):
        """
        Get the path to the local Diagrams.net viewer script
        
        This method will:
        1. Check if the script is bundled with the package
        2. Create the script file if it doesn't exist
        3. Return the path to the script
        """
        # Viewer script content (minimized version of viewer-static.min.js)
        viewer_script_content = """
        // Minimized Diagrams.net Viewer Script
        (function(){
            var mxIsElectron=window.navigator&&window.navigator.userAgent.indexOf('Electron')>=0;
            
            function mxCreateViewer(xml,container){
                if(typeof(window.Graph)!=='undefined')
                {
                    var graph=new window.Graph(container);
                    graph.setEnabled(false);
                    var codec=new window.mxCodec();
                    var node=codec.decode(window.mxUtils.parseXml(xml).documentElement);
                    graph.getModel().beginUpdate();
                    try{
                        graph.getModel().setRoot(node);
                    }finally{
                        graph.getModel().endUpdate();
                    }
                    graph.fit();
                    graph.view.setScale(1);
                }
            }

            window.embedDrawio=function(container){
                try{
                    var config=JSON.parse(container.getAttribute('data-mxgraph'));
                    mxCreateViewer(config.xml,container);
                }catch(e){
                    console.error('Drawio Viewer Error',e);
                }
            };

            // Embed all diagrams on page load
            if(document.readyState==='loading'){
                document.addEventListener('DOMContentLoaded',function(){
                    var containers=document.getElementsByClassName('mxgraph');
                    for(var i=0;i<containers.length;i++){
                        window.embedDrawio(containers[i]);
                    }
                });
            }else{
                var containers=document.getElementsByClassName('mxgraph');
                for(var i=0;i<containers.length;i++){
                    window.embedDrawio(containers[i]);
                }
            }
        })();
        """
        
        # Determine the package directory
        package_dir = os.path.dirname(__file__)
        
        # Create a 'static' subdirectory if it doesn't exist
        static_dir = os.path.join(package_dir, 'static')
        os.makedirs(static_dir, exist_ok=True)
        
        # Path for the viewer script
        viewer_script_path = os.path.join(static_dir, 'viewer-static.min.js')
        
        # Write the script if it doesn't exist
        if not os.path.exists(viewer_script_path):
            with open(viewer_script_path, 'w', encoding='utf-8') as f:
                f.write(viewer_script_content)
        
        return viewer_script_path

    def on_post_page(self, output_content, config, page, **kwargs):
        """
        Process page content to replace DrawIO diagram references with embedded diagrams
        """
        if ".drawio" not in output_content.lower():
            return output_content

        try:
            soup = BeautifulSoup(output_content, 'html.parser')
            diagrams = soup.findAll('img', src=re.compile(r'.*\.drawio', re.IGNORECASE))

            if not diagrams:
                return output_content

            # Add local DrawIO viewer library
            lib = soup.new_tag("script", src=self._get_relative_viewer_path(page))
            soup.body.append(lib)

            # Substitute images with embedded diagrams
            path = os.path.dirname(page.file.abs_src_path)
            for diagram in diagrams:
                try:
                    substituted_diagram = self.substitute_image(path, diagram['src'], diagram.get('alt'))
                    diagram.replace_with(BeautifulSoup(substituted_diagram, 'html.parser'))
                except Exception as e:
                    self.log.warning(f"Failed to process diagram {diagram['src']}: {e}")

            return str(soup)

        except Exception as e:
            self.log.error(f"Error processing page content: {e}")
            return output_content

    def _get_relative_viewer_path(self, page):
        """
        Get the relative path to the viewer script
        """
        # Calculate the relative path from the current page to the viewer script
        current_page_dir = os.path.dirname(page.file.dest_path)
        viewer_filename = os.path.basename(self.viewer_script_path)
        
        # For MkDocs, typically use a path in the site root
        return os.path.join('static', viewer_filename)

    def substitute_image(self, path: str, src: str, alt: str = None):
        """
        Substitute DrawIO image with embedded diagram
        """
        try:
            # Remove leading '../' if present
            src = src.lstrip('../')
            full_path = os.path.join(path, src)

            # Use cache to avoid re-parsing
            if full_path in self.parsed_diagrams_cache:
                diagram = self.parsed_diagrams_cache[full_path]
            else:
                diagram_xml = etree.parse(full_path)
                diagram = self.parse_diagram(diagram_xml, alt)
                self.parsed_diagrams_cache[full_path] = diagram

            escaped_xml = self.escape_diagram(diagram)
            return self._create_diagram_html(escaped_xml)

        except Exception as e:
            self.log.error(f"Error substituting image {src}: {e}")
            raise

    def parse_diagram(self, data, alt=None):
        """
        Parse specific diagram page if alt text is provided
        """
        if alt is None:
            return etree.tostring(data, encoding=str)

        try:
            mxfile = data.xpath("//mxfile")[0]
            pages = mxfile.xpath(f"//diagram[@name='{alt}']")

            if len(pages) == 1:
                parser = etree.XMLParser()
                result = parser.makeelement(mxfile.tag, mxfile.attrib)
                result.append(pages[0])
                return etree.tostring(result, encoding=str)
            elif len(pages) > 1:
                self.log.warning(f"Multiple pages found for name '{alt}'")
            else:
                self.log.warning(f"No page found for name '{alt}'")

            return etree.tostring(mxfile, encoding=str)

        except Exception as e:
            self.log.error(f"Error parsing diagram: {e}")
            return etree.tostring(data, encoding=str)

    def _create_diagram_html(self, escaped_xml):
        """
        Create HTML for embedded diagram
        """
        template = string.Template(
            "<div class=\"mxgraph\" style=\"max-width:100%;border:1px solid transparent;\" "
            "data-mxgraph=\"{&quot;highlight&quot;:&quot;#0000ff&quot;,&quot;nav&quot;:true,"
            "&quot;resize&quot;:true,&quot;toolbar&quot;:&quot;zoom layers tags lightbox&quot;,"
            "&quot;edit&quot;:&quot;_blank&quot;,&quot;xml&quot;:&quot;$xml_drawio&quot;}\">"
            "</div>"
        )
        return template.substitute(xml_drawio=escaped_xml)

    def escape_diagram(self, str_xml: str):
        """
        Escape XML for embedding in HTML
        """
        escape_map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&apos;'
        }
        return ''.join(escape_map.get(char, char) for char in str_xml).replace('\n', '')

    def on_files(self, files, config):
        """
        Copy the viewer script to the site's static directory
        """
        files.files.append(
            mkdocs.structure.files.File(
                src_path=self.viewer_script_path,
                dest_path=os.path.join('static', os.path.basename(self.viewer_script_path)),
                base_path=config['site_dir'],
                use_directory_urls=config['use_directory_urls']
            )
        )
        return files
